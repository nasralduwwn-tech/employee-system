# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime, date
from io import BytesIO
import os

# PDF & Arabic support
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import mm
import arabic_reshaper
from bidi.algorithm import get_display

app = Flask(__name__)
app.secret_key = 'services_office_secret_key_2026_change_me'
app.config['DATABASE'] = os.path.join(app.root_path, 'instance', 'office.db')

# Register Arabic font
FONT_PATH = os.path.join(app.root_path, 'fonts', 'NotoNaskhArabic-Regular.ttf')
pdfmetrics.registerFont(TTFont('NotoNaskh', FONT_PATH))

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'يجب تسجيل الدخول أولاً'


def get_db():
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'employee'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        check_in TEXT,
        check_out TEXT,
        work_date TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number TEXT UNIQUE NOT NULL,
        user_id INTEGER NOT NULL,
        client_name TEXT NOT NULL,
        service_desc TEXT NOT NULL,
        amount REAL NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')

    # Create default users if not exist
    c.execute('SELECT COUNT(*) FROM users')
    if c.fetchone()[0] == 0:
        users = [
            ('admin', generate_password_hash('admin123'), 'المدير', 'admin'),
            ('emp1', generate_password_hash('123456'), 'أحمد محمد', 'employee'),
            ('emp2', generate_password_hash('123456'), 'سارة علي', 'employee'),
            ('emp3', generate_password_hash('123456'), 'خالد حسن', 'employee'),
        ]
        c.executemany('INSERT INTO users (username, password, full_name, role) VALUES (?, ?, ?, ?)', users)

    conn.commit()
    conn.close()


class User(UserMixin):
    def __init__(self, id, username, full_name, role):
        self.id = id
        self.username = username
        self.full_name = full_name
        self.role = role


@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    if user:
        return User(user['id'], user['username'], user['full_name'], user['role'])
    return None


def reshape_arabic(text):
    if not text:
        return ''
    reshaped = arabic_reshaper.reshape(str(text))
    return get_display(reshaped)


def generate_invoice_pdf(invoice, employee_name):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Header
    c.setFont('NotoNaskh', 22)
    c.drawCentredString(width / 2, height - 40*mm, reshape_arabic('مكتب خدمات عامة'))
    
    c.setFont('NotoNaskh', 16)
    c.drawCentredString(width / 2, height - 55*mm, reshape_arabic('فاتورة خدمات'))

    # Line
    c.setStrokeColorRGB(0.2, 0.2, 0.5)
    c.setLineWidth(1.5)
    c.line(20*mm, height - 60*mm, width - 20*mm, height - 60*mm)

    # Invoice info
    y = height - 80*mm
    c.setFont('NotoNaskh', 12)
    
    info_lines = [
        f"رقم الفاتورة: {invoice['invoice_number']}",
        f"التاريخ: {invoice['created_at'][:10]}",
        f"الموظف: {employee_name}",
        f"اسم العميل: {invoice['client_name']}",
    ]
    
    for line in info_lines:
        c.drawRightString(width - 25*mm, y, reshape_arabic(line))
        y -= 10*mm

    # Service box
    y -= 5*mm
    c.setFont('NotoNaskh', 13)
    c.drawRightString(width - 25*mm, y, reshape_arabic('وصف الخدمة:'))
    y -= 8*mm
    
    # Wrap service description
    desc = invoice['service_desc']
    c.setFont('NotoNaskh', 11)
    # Simple wrap
    max_width = 150*mm
    words = desc.split()
    lines = []
    current = ''
    for w in words:
        test = current + ' ' + w if current else w
        if c.stringWidth(reshape_arabic(test), 'NotoNaskh', 11) < max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    
    for line in lines:
        c.drawRightString(width - 25*mm, y, reshape_arabic(line))
        y -= 7*mm

    # Amount
    y -= 15*mm
    c.setFont('NotoNaskh', 16)
    c.drawRightString(width - 25*mm, y, reshape_arabic(f"المبلغ: {invoice['amount']:.2f} ريال"))

    # Commission note (for internal, not shown to client ideally, but optional)
    y -= 20*mm
    c.setFont('NotoNaskh', 10)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawCentredString(width / 2, y, reshape_arabic('شكراً لتعاملكم معنا'))

    # Footer
    c.setFont('NotoNaskh', 9)
    c.drawCentredString(width / 2, 20*mm, reshape_arabic('مكتب خدمات عامة - جميع الحقوق محفوظة'))

    c.save()
    buffer.seek(0)
    return buffer


@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('employee_dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            user_obj = User(user['id'], user['username'], user['full_name'], user['role'])
            login_user(user_obj)
            flash('تم تسجيل الدخول بنجاح', 'success')
            return redirect(url_for('index'))
        flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('تم تسجيل الخروج', 'info')
    return redirect(url_for('login'))


@app.route('/employee')
@login_required
def employee_dashboard():
    if current_user.role != 'employee':
        return redirect(url_for('admin_dashboard'))
    
    conn = get_db()
    today = date.today().isoformat()
    
    # Today's attendance
    att = conn.execute(
        'SELECT * FROM attendance WHERE user_id = ? AND work_date = ?',
        (current_user.id, today)
    ).fetchone()
    
    # My recent invoices
    invoices = conn.execute(
        'SELECT * FROM invoices WHERE user_id = ? ORDER BY created_at DESC LIMIT 10',
        (current_user.id,)
    ).fetchall()
    
    # Monthly total so far
    month_start = date.today().replace(day=1).isoformat()
    total = conn.execute(
        'SELECT COALESCE(SUM(amount), 0) as total FROM invoices WHERE user_id = ? AND created_at >= ?',
        (current_user.id, month_start)
    ).fetchone()['total']
    
    conn.close()
    return render_template('employee.html', attendance=att, invoices=invoices, monthly_total=total)


@app.route('/checkin')
@login_required
def checkin():
    if current_user.role != 'employee':
        return redirect(url_for('index'))
    
    today = date.today().isoformat()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    conn = get_db()
    existing = conn.execute(
        'SELECT * FROM attendance WHERE user_id = ? AND work_date = ?',
        (current_user.id, today)
    ).fetchone()
    
    if existing and existing['check_in']:
        flash('تم تسجيل الحضور مسبقاً اليوم', 'warning')
    else:
        if existing:
            conn.execute('UPDATE attendance SET check_in = ? WHERE id = ?', (now, existing['id']))
        else:
            conn.execute(
                'INSERT INTO attendance (user_id, check_in, work_date) VALUES (?, ?, ?)',
                (current_user.id, now, today)
            )
        conn.commit()
        flash('تم تسجيل الحضور بنجاح', 'success')
    conn.close()
    return redirect(url_for('employee_dashboard'))


@app.route('/checkout')
@login_required
def checkout():
    if current_user.role != 'employee':
        return redirect(url_for('index'))
    
    today = date.today().isoformat()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    conn = get_db()
    existing = conn.execute(
        'SELECT * FROM attendance WHERE user_id = ? AND work_date = ?',
        (current_user.id, today)
    ).fetchone()
    
    if not existing or not existing['check_in']:
        flash('يجب تسجيل الحضور أولاً', 'warning')
    elif existing['check_out']:
        flash('تم تسجيل الانصراف مسبقاً اليوم', 'warning')
    else:
        conn.execute('UPDATE attendance SET check_out = ? WHERE id = ?', (now, existing['id']))
        conn.commit()
        flash('تم تسجيل الانصراف بنجاح', 'success')
    conn.close()
    return redirect(url_for('employee_dashboard'))


@app.route('/create_invoice', methods=['GET', 'POST'])
@login_required
def create_invoice():
    if current_user.role != 'employee':
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        client_name = request.form.get('client_name', '').strip()
        service_desc = request.form.get('service_desc', '').strip()
        amount = request.form.get('amount', '0').strip()
        
        if not client_name or not service_desc or not amount:
            flash('جميع الحقول مطلوبة', 'danger')
            return redirect(url_for('create_invoice'))
        
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except:
            flash('المبلغ غير صحيح', 'danger')
            return redirect(url_for('create_invoice'))
        
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # Simple invoice number
        inv_num = f"INV-{current_user.id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        conn = get_db()
        conn.execute(
            'INSERT INTO invoices (invoice_number, user_id, client_name, service_desc, amount, created_at) VALUES (?, ?, ?, ?, ?, ?)',
            (inv_num, current_user.id, client_name, service_desc, amount, now)
        )
        conn.commit()
        inv_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.close()
        
        flash(f'تم إنشاء الفاتورة رقم {inv_num} بنجاح', 'success')
        return redirect(url_for('download_invoice', invoice_id=inv_id))
    
    return render_template('create_invoice.html')


@app.route('/invoice/<int:invoice_id>/pdf')
@login_required
def download_invoice(invoice_id):
    conn = get_db()
    invoice = conn.execute('SELECT * FROM invoices WHERE id = ?', (invoice_id,)).fetchone()
    
    if not invoice:
        flash('الفاتورة غير موجودة', 'danger')
        conn.close()
        return redirect(url_for('index'))
    
    # Only owner or admin can download
    if current_user.role != 'admin' and invoice['user_id'] != current_user.id:
        flash('غير مصرح', 'danger')
        conn.close()
        return redirect(url_for('index'))
    
    emp = conn.execute('SELECT full_name FROM users WHERE id = ?', (invoice['user_id'],)).fetchone()
    conn.close()
    
    pdf_buffer = generate_invoice_pdf(invoice, emp['full_name'])
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"{invoice['invoice_number']}.pdf"
    )


@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('employee_dashboard'))
    
    conn = get_db()
    
    # Employees
    employees = conn.execute('SELECT * FROM users WHERE role = "employee"').fetchall()
    
    # Today's attendance
    today = date.today().isoformat()
    attendance = conn.execute('''
        SELECT a.*, u.full_name 
        FROM attendance a 
        JOIN users u ON a.user_id = u.id 
        WHERE a.work_date = ?
        ORDER BY a.check_in
    ''', (today,)).fetchall()
    
    # Recent invoices
    invoices = conn.execute('''
        SELECT i.*, u.full_name 
        FROM invoices i 
        JOIN users u ON i.user_id = u.id 
        ORDER BY i.created_at DESC LIMIT 15
    ''').fetchall()
    
    conn.close()
    return render_template('admin.html', employees=employees, attendance=attendance, invoices=invoices)


@app.route('/admin/commissions')
@login_required
def commissions():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    
    # Get month filter
    month = request.args.get('month', date.today().strftime('%Y-%m'))
    
    conn = get_db()
    
    results = conn.execute('''
        SELECT u.id, u.full_name, 
               COUNT(i.id) as inv_count,
               COALESCE(SUM(i.amount), 0) as total_sales,
               COALESCE(SUM(i.amount), 0) * 0.5 as commission
        FROM users u
        LEFT JOIN invoices i ON u.id = i.user_id AND strftime('%Y-%m', i.created_at) = ?
        WHERE u.role = 'employee'
        GROUP BY u.id
        ORDER BY total_sales DESC
    ''', (month,)).fetchall()
    
    # Total for the month
    grand = conn.execute('''
        SELECT COALESCE(SUM(amount), 0) as total 
        FROM invoices 
        WHERE strftime('%Y-%m', created_at) = ?
    ''', (month,)).fetchone()['total']
    
    conn.close()
    return render_template('commissions.html', results=results, month=month, grand_total=grand)


@app.route('/admin/attendance')
@login_required
def all_attendance():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    
    month = request.args.get('month', date.today().strftime('%Y-%m'))
    
    conn = get_db()
    records = conn.execute('''
        SELECT a.*, u.full_name 
        FROM attendance a 
        JOIN users u ON a.user_id = u.id 
        WHERE strftime('%Y-%m', a.work_date) = ?
        ORDER BY a.work_date DESC, a.check_in
    ''', (month,)).fetchall()
    conn.close()
    
    return render_template('attendance.html', records=records, month=month)


if __name__ == '__main__':
    os.makedirs(os.path.join(app.root_path, 'instance'), exist_ok=True)
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
