from flask import Flask, render_template, request, redirect, url_for, jsonify, make_response, send_file
from num2words import num2words
from io import BytesIO
from datetime import datetime
import pandas as pd
import pdfkit
import os
import math

from models import db, Invoice, Customer, InvoiceItem

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB limit

# ----------------------------
# Database setup
# ----------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

# Render may provide postgres:// but SQLAlchemy expects postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy with THIS app
db.init_app(app)

# Create tables at startup (required for gunicorn)
with app.app_context():
    db.create_all()

# ----------------------------
# PDFKit configuration
# ----------------------------
pdf_config = pdfkit.configuration()

# ----------------------------
# 🧮 Calculation Helper Function
# ----------------------------
def calculate_invoice(items, inv):
    subtotal = sum(float(item.amount) for item in items)
    fuel_charge = subtotal * (inv.fuel_percentage / 100)
    gst_type = inv.gst_type
    additional_charges = inv.additional_charges or 0
    tax_base = subtotal + fuel_charge + additional_charges
    gst_rate = inv.gst_rate or 0

    # GST Calculations
    if gst_type == "IGST":
        igst = tax_base * (gst_rate / 100)
        cgst = sgst = 0
        igst_rate = gst_rate
        cgst_rate = sgst_rate = 0
    elif gst_type == "NA":
        igst = cgst = sgst = 0
        igst_rate = cgst_rate = sgst_rate = 0
    else:  # CGST + SGST
        igst = 0
        cgst = tax_base * ((gst_rate / 2) / 100)
        sgst = tax_base * ((gst_rate / 2) / 100)
        igst_rate = 0
        cgst_rate = sgst_rate = round((gst_rate / 2))

    bill_amount = tax_base + igst + cgst + sgst

    return {
        "subtotal": round(subtotal, 2),
        "fuel_charge": round(fuel_charge, 2),
        "igst": round(igst, 2),
        "cgst": round(cgst, 2),
        "sgst": round(sgst, 2),
        "igst_rate": igst_rate,
        "sgst_rate": sgst_rate,
        "cgst_rate": cgst_rate,
        "bill_amount": math.ceil(bill_amount)
    }

# ----------------------------
# ROUTE: Home page (invoice list)
# ----------------------------
@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 15  # show 15 invoices per page

    search = request.args.get('search', '').strip()
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    query = Invoice.query.join(Customer)

    if search:
        query = query.filter(
            (Invoice.invoice_no.like(f"%{search}%")) |
            (Customer.name.like(f"%{search}%"))
        )

    if start_date and end_date:
        query = query.filter(Invoice.invoice_date.between(start_date, end_date))

    pagination = query.order_by(Invoice.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
    invoices = pagination.items

    invoice_data = []
    total_amount = 0
    for inv in invoices:
        items = inv.items
        totals = calculate_invoice(items, inv)
        invoice_data.append({"invoice": inv, "totals": totals})
        total_amount += totals["bill_amount"]

    total_invoices = query.count()

    return render_template(
        'index.html',
        invoice_data=invoice_data,
        pagination=pagination,
        total_invoices=total_invoices,
        total_amount=total_amount,
        search=search,
        start_date=start_date,
        end_date=end_date
    )

# ----------------------------
# ROUTE: Create New Invoice
# ----------------------------
@app.route('/new-invoice', methods=['GET', 'POST'])
def new_invoice():
    customers = Customer.query.all()
    today = datetime.now().strftime("%Y-%m-%d")
    next_invoice_no = Invoice.generate_invoice_no()

    if request.method == 'POST':
        customer_name = request.form.get('customer_name')
        customer = Customer.query.filter_by(name=customer_name).first()
        if not customer:
            return "Customer not found", 400

        inv = Invoice(
            invoice_no=request.form.get('invoice_no'),
            from_date=request.form.get('from_date'),
            to_date=request.form.get('to_date'),
            invoice_date=request.form.get('invoice_date'),
            customer_id=customer.id,
            fuel_percentage=request.form.get('fuel_percentage'),
            gst_type=request.form.get('gst_type'),
            gst_rate=request.form.get('gst_rate'),
            additional_charges=request.form.get('additional_charges'),
            remarks=request.form.get('remarks'),
            created_at=datetime.now()
        )

        db.session.add(inv)
        db.session.commit()

        # Add invoice items
        item_dates = request.form.getlist('item_date[]')
        awb_nos = request.form.getlist('awb_no[]')
        destinations = request.form.getlist('destination[]')
        weights = request.form.getlist('weight[]')
        amounts = request.form.getlist('item_amount[]')

        for i in range(len(item_dates)):
            item = InvoiceItem(
                invoice_id=inv.id,
                date=item_dates[i],
                awb_no=awb_nos[i],
                destination=destinations[i],
                weight=weights[i],
                amount=float(amounts[i]) if amounts[i].replace('.', '', 1).isdigit() else 0.0
            )
            db.session.add(item)

        db.session.commit()
        return redirect(url_for('index'))

    return render_template('invoice_form.html', customers=customers, today=today, next_invoice_no=next_invoice_no)

# ----------------------------
# MAIN ENTRY POINT
# ----------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
