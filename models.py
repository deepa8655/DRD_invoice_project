from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Customer(db.Model):
    __tablename__ = 'customers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100))
    mobile = db.Column(db.String(20))
    address = db.Column(db.String(200))
    gst_no = db.Column(db.String(50))
    pan_no = db.Column(db.String(50))
    state = db.Column(db.String(50))
    state_code = db.Column(db.String(10))

    invoices = db.relationship('Invoice', backref='customer', lazy=True)

    def __repr__(self):
        return f'<Customer {self.name}>'


class Invoice(db.Model):
    __tablename__ = 'invoices'
    id = db.Column(db.Integer, primary_key=True)
    invoice_no = db.Column(db.String(50), unique=True, nullable=False)
    invoice_date = db.Column(db.Date, default=datetime.utcnow)

    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)

    from_date = db.Column(db.Date)
    to_date = db.Column(db.Date)
    fuel_percentage = db.Column(db.Integer)
    gst_type = db.Column(db.Text)
    remarks = db.Column(db.Text)
    gst_rate = db.Column(db.Integer)
    additional_charges=db.Column(db.Float)
    payment_status = db.Column(db.String(20), default='Unpaid')
    created_at = db.Column(db.DateTime)

    items = db.relationship('InvoiceItem', backref='invoice', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Invoice {self.invoice_no}>'

    @staticmethod
    def generate_invoice_no():
        last = Invoice.query.order_by(Invoice.id.desc()).first()
        if not last or not last.invoice_no:
            return "INV-0001"
        try:
            num = int(last.invoice_no.split('-')[-1]) + 1
            return f"INV-{num:04d}"
        except Exception:
            # fallback
            return f"INV-{last.id + 1:04d}"


class InvoiceItem(db.Model):
    __tablename__ = 'invoice_items'
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    date = db.Column(db.Date)
    awb_no = db.Column(db.String(200), nullable=False)
    destination = db.Column(db.String(200), nullable=False)
    weight = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, default=0.0)

    def __repr__(self):
        return f'<InvoiceItem {self.awb_no} - {self.amount}>'

    @property
    def line_total(self):
        return round(self.amount or 0.0, 2)
