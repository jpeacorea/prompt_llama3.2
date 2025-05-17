import json
import os
from io import BytesIO # Para manejar el PDF en memoria
from datetime import datetime

import requests
from flask import Flask, jsonify, request, send_file, send_from_directory, render_template, make_response
from fpdf import FPDF

app = Flask(__name__)

# --- CONFIGURACION ---

LLAMA_API_KEY = "AQUI URL DE LA API DE LLAMA"  # Cambia esto por la URL de tu API de Llama

# --- FUNCIÓN PARA CREAR PDF ---

def create_invoice_pdf(invoice_data):
    """
    Genera un archivo PDF de factura a partir de datos JSON.

    Args:
        invoice_data (dict): Un diccionario con los datos de la factura.
                             Se espera una estructura como:
                             {
                                 "invoice_number": "FACT-001",
                                 "customer_name": "Cliente Ejemplo S.A.",
                                 "customer_address": "Calle Falsa 123, Ciudad",
                                 "items": [
                                     {"description": "Producto A", "quantity": 2, "unit_price": 50.0},
                                     {"description": "Servicio B", "quantity": 1, "unit_price": 150.0}
                                 ],
                                 "tax_rate": 0.15 # Ejemplo 15% de IVA
                             }
    Returns:
        bytes: El contenido del archivo PDF como bytes.
        None: Si los datos de entrada son inválidos.
    """
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)

        json_object = json.loads(invoice_data.__str__())
        print("JSON", invoice_data)

        # Título
        pdf.set_font("Helvetica", 'B', 16)
        pdf.cell(0, 10, "FACTURA", ln=True, align='C')
        pdf.ln(10)

        # Información básica
        pdf.set_font("Helvetica", size=10)
        invoice_num = json_object["numero_factura"]
        invoice_date = datetime.now().strftime("%Y-%m-%d")
        pdf.cell(0, 5, f"Factura No: {invoice_num}", ln=True, align='R')
        pdf.cell(0, 5, f"Fecha: {invoice_date}", ln=True, align='R')
        pdf.ln(5)

        # Datos del Cliente
        pdf.set_font("Helvetica", 'B', 11)
        pdf.cell(0, 6, "Cliente:", ln=True)
        pdf.set_font("Helvetica", size=10)
        pdf.cell(0, 5, json_object["nombre_cliente"], ln=True)
        pdf.cell(0, 5, json_object["direccion"], ln=True)
        # Puedes añadir más campos como RUC/CIF si están en el JSON
        pdf.ln(10)

        # Cabecera de la tabla de items
        pdf.set_font("Helvetica", 'B', 10)
        pdf.cell(80, 7, "Descripcion", border=1)
        pdf.cell(20, 7, "Cant.", border=1, align='C')
        pdf.cell(40, 7, "Precio Unit.", border=1, align='R')
        pdf.cell(40, 7, "Total", border=1, align='R')
        pdf.ln()

        # Items de la factura
        pdf.set_font("Helvetica", size=10)
        subtotal = 0
        items = json_object["detalles"]
        if not isinstance(items, list):
             print("Warning: 'items' no es una lista válida en invoice_data.")
             items = [] # Asegura que sea una lista para evitar errores

        for item in items:
             # Validaciones básicas de tipo
            try:
                desc = str(item["descripcion"])
                qty = float(item["cantidad"])
                price = float(item["precio_unitario"])
                total_item = qty * price
                subtotal += total_item

                # Limitar longitud de descripción para que quepa
                max_desc_width = 78 # Ancho aprox disponible en la celda de descripción
                if pdf.get_string_width(desc) > max_desc_width:
                     # Simple truncamiento (se puede mejorar con MultiCell)
                     while pdf.get_string_width(desc + '...') > max_desc_width:
                          desc = desc[:-1]
                     desc += '...'

                pdf.cell(80, 6, desc, border=1)
                pdf.cell(20, 6, str(qty), border=1, align='C')
                pdf.cell(40, 6, f"{price:.2f}", border=1, align='R')
                pdf.cell(40, 6, f"{total_item:.2f}", border=1, align='R')
                pdf.ln()
            except (ValueError, TypeError) as item_err:
                print(f"Error procesando item: {item}. Error: {item_err}")
                # Podrías añadir una línea en el PDF indicando el error o saltar el item

        # Totales
        pdf.ln(5)
        tax_rate = float(json_object["iva"]["tasa"]) # Asegura que sea float
        tax_amount = subtotal * tax_rate
        grand_total = subtotal + tax_amount

        pdf.set_font("Helvetica", 'B', 10)
        pdf.cell(140, 7, "Subtotal:", align='R')
        pdf.cell(40, 7, f"{subtotal:.2f}", border=1, align='R')
        pdf.ln()
        pdf.cell(140, 7, f"IVA ({tax_rate*100:.0f}%):", align='R')
        pdf.cell(40, 7, f"{tax_amount:.2f}", border=1, align='R')
        pdf.ln()
        pdf.cell(140, 7, "Total General:", align='R')
        pdf.cell(40, 7, f"{grand_total:.2f}", border=1, align='R')
        pdf.ln()

        # Generar el PDF como bytes
        # Usamos BytesIO para asegurar compatibilidad
        buffer = BytesIO()
        pdf.output(buffer)
        buffer.seek(0)
        return buffer.getvalue()

    except Exception as e:
        print(f"Error generando PDF: {e}")
        print(f"Datos recibidos: {invoice_data}") # Log para depuración
        return None # Indica que hubo un error

# --- ENDPOINTS ---
@app.route("/")
def index():
    """ Sirve la pagina HTML principal """
    return render_template('index.html')


@app.route("/api/generate", methods=["POST"])
def generate_api():

    """
    Recibe el prompt, obtiene JSON de Llama, genera PDF y lo devuelve.
    """
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    prompt = data.get('prompt')

    if not prompt:
        return jsonify({"error": "Missing 'prompt' in request body"}), 400

    print(f"Recibido prompt: {prompt}")

    # --- Llamada a la API externa de Llama 3.2 ---
    try:
        payload = {
            "model": "llama3.2",
            "prompt": prompt,
            "format": "json",
            "stream": False
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}  # Pedimos JSON

        response = requests.post(
            f"{LLAMA_API_KEY}/api/generate",
            headers=headers,
            json=payload,
        )  # Timeout más largo
        response.raise_for_status()

        # --- Procesamiento de la respuesta de Llama ---
        try:
            # Intenta parsear la respuesta como JSON directamente
            api_response_data = response.json()
            # !!! ASUNCIÓN CLAVE: La respuesta JSON de Llama es directamente el diccionario invoice_data !!!
            # Si Llama envuelve el JSON dentro de otra clave (ej: {"response": "{...}"}), necesitas extraerlo:
            # raw_response = api_response_data.get('response')
            # invoice_data = json.loads(raw_response)

            # Por simplicidad, asumimos que api_response_data ya tiene la estructura esperada
            invoice_data = api_response_data
            print(f"JSON de Llama recibido y parseado: {invoice_data}")  # Log

        except json.JSONDecodeError:
            # Si la respuesta no es JSON válido, intenta obtener el texto
            print(f"Respuesta de Llama no es JSON válido: {response.text}")
            return jsonify({"error": "La API de Llama no devolvió un JSON válido."}), 500
        except Exception as parse_err:
            print(f"Error procesando JSON de Llama: {parse_err}")
            return jsonify({"error": f"Error procesando respuesta de Llama: {parse_err}"}), 500

        # --- Generación del PDF ---
        pdf_content = create_invoice_pdf(invoice_data.get("response"))

        if pdf_content is None:
            # Error durante la creación del PDF (ya logueado en create_invoice_pdf)
            # Podría ser por datos inválidos en el JSON de Llama
            return jsonify(
                {"error": "Error al generar el PDF. Verifica la estructura del JSON devuelto por Llama."}), 500

        # --- Devolver el PDF ---
        pdf_filename = f"factura_{invoice_data.get('invoice_number', 'sin_numero')}.pdf"
        response_pdf = make_response(pdf_content)
        response_pdf.headers['Content-Type'] = 'application/pdf'
        response_pdf.headers['Content-Disposition'] = f'attachment; filename="{pdf_filename}"'
        print(f"Enviando PDF: {pdf_filename}")  # Log
        return response_pdf

    except requests.exceptions.RequestException as e:
        print(f"Error al contactar la API de Llama: {e}")
        return jsonify({"error": f"Error al contactar la API de Llama: {e}"}), 500
    except Exception as e:
        # Captura errores generales, incluyendo los raise_for_status
        print(f"Error inesperado en /generate: {e}")
        # Intenta devolver el texto del error si es posible (ej. de un 4xx/5xx)
        error_text = getattr(e.response, 'text', str(e))
        status_code = getattr(e.response, 'status_code', 500)
        return jsonify({"error": f"Error procesando la solicitud: {error_text}"}), status_code


@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)


# --- INICIO DE LA APLICACION ---
if __name__ == "__main__":
    app.run(port=int(os.environ.get('PORT', 80)))
