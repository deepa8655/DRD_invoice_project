from flask import Flask, render_template, request, redirect, url_for, jsonify, make_response, send_file
from num2words import num2words
from io import BytesIO
import pandas as pd
from datetime import datetime
from models import db, Invoice, Customer, InvoiceItem
import pdfkit
import os
import math

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

# ----------------------------
# Database (Render compatible)
# ----------------------------
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# ----------------------------
# PDFKit (Linux / Render)
# ----------------------------
pdf_config = pdfkit.configuration()

# ----------------------------
# Helper: Invoice calculation
# ----------------------------
def calculate_invoice(items, inv):
    subtotal = sum(float(item.amount) for item in items)
    fuel_charge = subtotal * (float(inv.fuel_percentage or 0) / 100)
    additional_charges = float(inv.additional_charges or 0)
    tax_base = subtotal + fuel_charge + additional_charges
    gst_rate = float(inv.gst_rate or 0)

    igst = cgst = sgst = 0
    igst_rate = cgst_rate = sgst_rate = 0

    if inv.gst_type == "IGST":
        igst = tax_base * gst_rate / 100
        igst_rate = gst_rate
    elif inv.gst_type == "CGST":
        cgst = tax_base * (gst_rate / 2) / 100
        sgst = tax_base * (gst_rate / 2) / 100
        cgst_rate = sgst_rate = gst_rate / 2

    bill_amount = tax_base + igst + cgst + sgst

    return {
        "subtotal": round(subtotal, 2),
        "fuel_charge": round(fuel_charge, 2),
        "igst": round(igst, 2),
        "cgst": round(cgst, 2),
        "sgst": round(sgst, 2),
        "igst_rate": igst_rate,
        "cgst_rate": cgst_rate,
        "sgst_rate": sgst_rate,
        "bill_amount": math.ceil(bill_amount)
    }

# ----------------------------
# Routes
# ----------------------------
@app.route('/')
def index():
    invoices = Invoice.query.order_by(Invoice.id.desc()).all()
    invoice_data = []
    for inv in invoices:
        totals = calculate_invoice(inv.items, inv)
        invoice_data.append({"invoice": inv, "totals": totals})
    return render_template('index.html', invoice_data=invoice_data)

@app.route('/invoice/<int:id>/pdf')
def generate_invoice_pdf(id):
    inv = Invoice.query.get_or_404(id)
    totals = calculate_invoice(inv.items, inv)
    amount_in_words = num2words(totals['bill_amount'], lang='en_IN').title() + ' Only'

    html = render_template(
        'invoice_template.html',
        inv=inv,
        customer=inv.customer,
        items=inv.items,
        totals=totals,
        amount_in_words=amount_in_words
    )

    options = {
        'page-size': 'A4',
        'encoding': 'UTF-8',
        'enable-local-file-access': ''
    }

    pdf = pdfkit.from_string(html, False, configuration=pdf_config, options=options)
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline; filename=invoice.pdf'
    return response

# ----------------------------
# App start (Render)
# ----------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
