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
# ROUTE: Fetch Customer Details (AJAX)
# ----------------------------
@app.route('/customer/<int:customer_id>')
def get_customer(customer_id):
    cust = Customer.query.get(customer_id)
    if not cust:
        return jsonify({"error": "Customer not found"}), 404
    return jsonify({
        "id": cust.id,
        "name": cust.name,
        "gst_no": cust.gst_no,
        "pan_no": cust.pan_no,
        "state": cust.state
    })
@app.route('/customers', endpoint='manage_customers')
def manage_customers():
    customers = Customer.query.all()
    return render_template('customers.html', customers=customers, customer=None)



@app.route('/add_customer', methods=['POST'])
def add_customer():
    id = request.form.get('id')
    name = request.form.get('name')
    gst_no = request.form.get('gst_no')
    pan_no = request.form.get('pan_no')
    state = request.form.get('state')
    state_code = request.form.get('state_code')
    address = request.form.get('address')

    if id:  # Edit existing
        cust = Customer.query.get(id)
        cust.name = name
        cust.gst_no = gst_no
        cust.pan_no = pan_no
        cust.state = state
        cust.state_code = state_code
        cust.address = address
    else:  # Add new
        cust = Customer(name=name, gst_no=gst_no, pan_no=pan_no, state=state,state_code=state_code, address=address)
        db.session.add(cust)
    db.session.commit()
    return redirect(url_for('manage_customers'))

@app.route('/edit_customer/<int:id>')
def edit_customer(id):
    cust = Customer.query.get_or_404(id)
    customers = Customer.query.all()
    return render_template('customers.html', customer=cust, customers=customers)


@app.route('/delete_customer/<int:id>')
def delete_customer(id):
    cust = Customer.query.get_or_404(id)
    db.session.delete(cust)
    db.session.commit()
    return redirect(url_for('manage_customers'))


# ----------------------------
# ROUTE: Generate Invoice PDF (with calculations)
# ----------------------------
@app.route('/invoice/<int:id>/pdf')
def generate_invoice_pdf(id):
    inv = Invoice.query.get_or_404(id)
    customer = inv.customer
    items = inv.items

    # 🧮 Perform calculation here before rendering
    totals = calculate_invoice(items, inv)
    amount_in_words = num2words(totals["bill_amount"], to='cardinal', lang='en_IN').title() + " Only"


    rendered_html = render_template(
        'invoice_template.html',
        inv=inv,
        customer=customer,
        items=items,
        totals=totals,
        amount_in_words=amount_in_words
    )

    options = {
        'page-size': 'A4',
        'margin-top': '10mm',
        'margin-right': '10mm',
        'margin-bottom': '10mm',
        'margin-left': '10mm',
        'encoding': "UTF-8",
        'enable-local-file-access': ''
    }

    pdf = pdfkit.from_string(rendered_html, False, configuration=pdf_config, options=options)

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename={customer.name}_{inv.invoice_no}.pdf'
    return response


# ----------------------------
# ROUTE: Edit Existing Invoice
# ----------------------------
@app.route('/invoice/<int:id>/edit', methods=['GET', 'POST'])
def edit_invoice(id):
    inv = Invoice.query.get_or_404(id)
    customers = Customer.query.all()
    items = inv.items

    if request.method == 'POST':
        # Update main invoice details
        inv.invoice_no = request.form.get('invoice_no')
        inv.invoice_date = request.form.get('invoice_date')
        inv.from_date = request.form.get('from_date')
        inv.to_date = request.form.get('to_date')
        inv.fuel_percentage = request.form.get('fuel_percentage')
        inv.gst_type = request.form.get('gst_type')
        inv.gst_rate = request.form.get('gst_rate')
        inv.additional_charges = request.form.get('additional_charges')
        inv.remarks = request.form.get('remarks')

        # Update customer
        customer_name = request.form.get('customer_name')
        customer = Customer.query.filter_by(name=customer_name).first()
        if customer:
            inv.customer_id = customer.id

        # Clear old items
        InvoiceItem.query.filter_by(invoice_id=inv.id).delete()

        # Add new/updated items
        item_dates = request.form.getlist('item_date[]')
        awb_nos = request.form.getlist('awb_no[]')
        destinations = request.form.getlist('destination[]')
        weights = request.form.getlist('weight[]')
        amounts = request.form.getlist('item_amount[]')

        for i in range(len(item_dates)):
            if not item_dates[i]:
                continue
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
        print(f"✅ Invoice {inv.invoice_no} updated successfully")
        return redirect(url_for('index'))

    return render_template('invoice_edit.html', inv=inv, customers=customers, items=items)

# ----------------------------
# ROUTE: Save Invoice PDF to File
# ----------------------------
@app.route('/invoice/<int:id>/save')
def save_invoice_pdf(id):
    inv = Invoice.query.get_or_404(id)
    customer = inv.customer
    items = inv.items

    # --- Calculate totals and words ---
    totals = calculate_invoice(items, inv)
    amount_in_words = num2words(
        totals["bill_amount"],
        to='cardinal',
        lang='en_IN'
    ).title() + " Only"

    # --- Render invoice HTML ---
    rendered_html = render_template(
        'invoice_template.html',
        inv=inv,
        customer=customer,
        items=items,
        totals=totals,
        amount_in_words=amount_in_words
    )

    # --- Folder to store PDF ---
    save_dir = os.path.join(os.getcwd(), "invoices")
    os.makedirs(save_dir, exist_ok=True)

    # --- Safe filename (no spaces or invalid characters) ---
    safe_name = customer.name.replace(" ", "_")
    safe_invoice_no = str(inv.invoice_no).replace("/", "-")
    file_path = os.path.join(save_dir, f"{safe_name}_{safe_invoice_no}.pdf")

    # --- wkhtmltopdf options (IMPORTANT FOR CSS, IMAGES, JS) ---
    options = {
        'page-size': 'A4',
        'margin-top': '10mm',
        'margin-right': '10mm',
        'margin-bottom': '10mm',
        'margin-left': '10mm',
        'encoding': "UTF-8",
        'enable-local-file-access': ''
    }

    # --- Generate PDF ---
    pdfkit.from_string(
        rendered_html,
        file_path,
        configuration=pdf_config,
        options=options
    )

    return f"✅ PDF saved successfully at: {file_path}"


@app.route('/upload_items', methods=['POST'])
def upload_items():
    import pandas as pd
    from datetime import datetime

    if 'excel_file' not in request.files:
        return "No file part", 400

    file = request.files['excel_file']
    if file.filename == '':
        return "No selected file", 400

    # Read Excel
    df = pd.read_excel(file)

    # Normalize column names
    df.columns = [c.strip().title() for c in df.columns]

    items = []

    for _, row in df.iterrows():
        raw_date = row.get('Date')

        # --- DATE PARSING START ---
        if pd.isna(raw_date) or str(raw_date).strip() in ['', 'NaT', 'nan', 'NaN']:
            date_value = None
        else:
            try:
                if isinstance(raw_date, pd.Timestamp):
                    date_value = raw_date.date()
                elif isinstance(raw_date, str):
                    date_value = None
                    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y"):
                        try:
                            date_value = datetime.strptime(raw_date.strip(), fmt).date()
                            break
                        except ValueError:
                            continue
                    if date_value is None:
                        # fallback to pandas
                        parsed = pd.to_datetime(raw_date, errors='coerce', dayfirst=True)
                        date_value = parsed.date() if pd.notna(parsed) else None
                else:
                    date_value = None
            except Exception as e:
                print("⚠️ Date conversion failed for:", raw_date, "| Error:", e)
                date_value = None
        # --- DATE PARSING END ---

        item = {
            "date": date_value,
            "awb_no": row.get("Awb No") or "",
            "destination": row.get("Destination") or "",
            "weight": row.get("Weight") or 0,
            "amount": row.get("Amount") or 0
        }
        items.append(item)

    # Debug print
    print("✅ Uploaded items:", items[:5])

    # You can save this `items` list to session or DB as needed
    return jsonify({"message": "File uploaded successfully", "items": items})


@app.route('/download_template')
def download_template():
    data = {
        'Date': [],
        'AWB No': [],
        'Destination': [],
        'Weight': [],
        'Amount': []
    }
    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name='invoice_template.xlsx')

# ----------------------------
# ROUTE: Delete Invoice
# ----------------------------
@app.route('/invoice/<int:id>/delete', methods=['POST'])
def delete_invoice(id):
    inv = Invoice.query.get_or_404(id)
    
    # Delete associated items first (due to foreign key constraint)
    InvoiceItem.query.filter_by(invoice_id=inv.id).delete()
    db.session.delete(inv)
    db.session.commit()
    
    return redirect(url_for('index'))

# ----------------------------
# MAIN ENTRY POINT
# ----------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
