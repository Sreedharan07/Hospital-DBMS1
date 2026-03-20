from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import date

app = Flask(__name__)
app.secret_key = 'hospital_secret_key_2024'

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'root'  # Change this
app.config['MYSQL_DB'] = 'hospital_db'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)

def nv(key):
    v = request.form.get(key, '').strip()
    return v if v else None

# ─── Auth Decorators ───────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def receptionist_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'receptionist':
            flash('Access denied. Receptionists only.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

def doctor_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'doctor':
            flash('Access denied. Doctors only.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

# ─── Auth ──────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return redirect(url_for('dashboard') if 'user_id' in session else url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s", (request.form['username'],))
        user = cur.fetchone()
        cur.close()
        if user and check_password_hash(user['password_hash'], request.form['password']):
            session.update({'user_id': user['id'], 'username': user['username'],
                            'full_name': user['full_name'], 'role': user['role']})
            flash(f'Welcome back, {user["full_name"]}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid credentials.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── Dashboard ─────────────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    cur = mysql.connection.cursor()
    cur.execute("SELECT COUNT(*) as c FROM patients")
    total_patients = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) as c FROM appointments WHERE appointment_date=CURDATE() AND status='scheduled'")
    today_appointments = cur.fetchone()['c']
    cur.execute("SELECT COUNT(*) as c FROM doctors")
    total_doctors = cur.fetchone()['c']
    cur.execute("SELECT COALESCE(SUM(total),0) as r FROM billing WHERE status='paid' AND MONTH(billing_date)=MONTH(CURDATE())")
    monthly_revenue = cur.fetchone()['r']

    if session.get('role') == 'doctor':
        cur.execute("SELECT d.id FROM doctors d JOIN users u ON d.user_id=u.id WHERE u.id=%s", (session['user_id'],))
        row = cur.fetchone()
        doc_id = row['id'] if row else 0
        cur.execute("""SELECT a.*, p.first_name, p.last_name, u.full_name as doctor_name
                       FROM appointments a JOIN patients p ON a.patient_id=p.id
                       JOIN doctors d ON a.doctor_id=d.id JOIN users u ON d.user_id=u.id
                       WHERE a.doctor_id=%s AND a.status='scheduled'
                       ORDER BY a.appointment_date, a.appointment_time LIMIT 10""", (doc_id,))
    else:
        cur.execute("""SELECT a.*, p.first_name, p.last_name, u.full_name as doctor_name
                       FROM appointments a JOIN patients p ON a.patient_id=p.id
                       JOIN doctors d ON a.doctor_id=d.id JOIN users u ON d.user_id=u.id
                       WHERE a.status='scheduled'
                       ORDER BY a.appointment_date, a.appointment_time LIMIT 10""")
    upcoming = cur.fetchall()
    cur.close()
    return render_template('dashboard.html', total_patients=total_patients,
        today_appointments=today_appointments, total_doctors=total_doctors,
        monthly_revenue=monthly_revenue, upcoming=upcoming)

# ─── Patients ──────────────────────────────────────────────────────────────────
@app.route('/patients')
@login_required
def patients():
    search = request.args.get('search', '')
    cur = mysql.connection.cursor()
    if search:
        cur.execute("SELECT * FROM patients WHERE first_name LIKE %s OR last_name LIKE %s OR phone LIKE %s ORDER BY created_at DESC",
                    (f'%{search}%', f'%{search}%', f'%{search}%'))
    else:
        cur.execute("SELECT * FROM patients ORDER BY created_at DESC")
    patients_list = cur.fetchall()
    cur.close()
    return render_template('patients.html', patients=patients_list, search=search)

@app.route('/patients/add', methods=['GET', 'POST'])
@receptionist_required
def add_patient():
    if request.method == 'POST':
        cur = mysql.connection.cursor()
        cur.execute("""INSERT INTO patients (first_name,last_name,dob,gender,phone,email,address,blood_group,allergies,emergency_contact,emergency_phone)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (request.form['first_name'].strip(), request.form['last_name'].strip(),
                     nv('dob'), nv('gender'), nv('phone'), nv('email'),
                     nv('address'), nv('blood_group'), nv('allergies'),
                     nv('emergency_contact'), nv('emergency_phone')))
        mysql.connection.commit()
        cur.close()
        flash('Patient added!', 'success')
        return redirect(url_for('patients'))
    return render_template('patient_form.html', patient=None, action='Add')

@app.route('/patients/edit/<int:pid>', methods=['GET', 'POST'])
@receptionist_required
def edit_patient(pid):
    cur = mysql.connection.cursor()
    if request.method == 'POST':
        cur.execute("""UPDATE patients SET first_name=%s,last_name=%s,dob=%s,gender=%s,phone=%s,
                       email=%s,address=%s,blood_group=%s,allergies=%s,emergency_contact=%s,emergency_phone=%s WHERE id=%s""",
                    (request.form['first_name'].strip(), request.form['last_name'].strip(),
                     nv('dob'), nv('gender'), nv('phone'), nv('email'),
                     nv('address'), nv('blood_group'), nv('allergies'),
                     nv('emergency_contact'), nv('emergency_phone'), pid))
        mysql.connection.commit()
        cur.close()
        flash('Patient updated!', 'success')
        return redirect(url_for('patients'))
    cur.execute("SELECT * FROM patients WHERE id=%s", (pid,))
    patient = cur.fetchone()
    cur.close()
    return render_template('patient_form.html', patient=patient, action='Edit')

@app.route('/patients/delete/<int:pid>', methods=['POST'])
@receptionist_required
def delete_patient(pid):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM patients WHERE id=%s", (pid,))
    mysql.connection.commit()
    cur.close()
    flash('Patient removed.', 'success')
    return redirect(url_for('patients'))

@app.route('/patients/view/<int:pid>')
@login_required
def view_patient(pid):
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM patients WHERE id=%s", (pid,))
    patient = cur.fetchone()
    cur.execute("""SELECT a.*, u.full_name as doctor_name, d.specialization
                   FROM appointments a JOIN doctors d ON a.doctor_id=d.id
                   JOIN users u ON d.user_id=u.id WHERE a.patient_id=%s ORDER BY a.appointment_date DESC""", (pid,))
    appts = cur.fetchall()
    cur.execute("SELECT * FROM billing WHERE patient_id=%s ORDER BY billing_date DESC", (pid,))
    bills = cur.fetchall()
    cur.close()
    return render_template('patient_view.html', patient=patient, appointments=appts, bills=bills)

# ─── Doctor: Complete appointment → auto-bill → discharge patient ──────────────
@app.route('/appointments/complete/<int:aid>', methods=['POST'])
@doctor_required
def complete_appointment(aid):
    notes    = request.form.get('notes', '').strip()
    fee      = request.form.get('fee', '500').strip()
    try: fee = float(fee)
    except: fee = 500.0

    cur = mysql.connection.cursor()
    cur.execute("""SELECT a.*, p.first_name, p.last_name, p.id as pid
                   FROM appointments a JOIN patients p ON a.patient_id=p.id WHERE a.id=%s""", (aid,))
    appt = cur.fetchone()
    if not appt:
        cur.close()
        flash('Appointment not found.', 'error')
        return redirect(url_for('appointments'))

    pid = appt['pid']
    patient_name = f"{appt['first_name']} {appt['last_name']}"

    # Mark appointment completed with doctor notes
    cur.execute("UPDATE appointments SET status='completed', notes=%s WHERE id=%s", (notes, aid))

    # Auto-create bill
    cur.execute("SELECT id FROM billing WHERE appointment_id=%s", (aid,))
    existing = cur.fetchone()
    if not existing:
        cur.execute("""INSERT INTO billing (patient_id,appointment_id,description,amount,discount,tax,total,status,payment_method,billing_date)
                       VALUES (%s,%s,%s,%s,0,0,%s,'pending','cash',%s)""",
                    (pid, aid, f'Consultation – {patient_name}', fee, fee, date.today()))
        bill_id = cur.lastrowid
    else:
        bill_id = existing['id']

    # Discharge: delete patient record
    cur.execute("DELETE FROM patients WHERE id=%s", (pid,))
    # Auto-delete the completed appointment from the list
    cur.execute("DELETE FROM appointments WHERE id=%s", (aid,))
    mysql.connection.commit()
    cur.close()
    flash(f'{patient_name} marked complete & discharged. Bill ready to print.', 'success')
    return redirect(url_for('print_bill_safe', bid=bill_id))

# ─── Print Bill ────────────────────────────────────────────────────────────────
@app.route('/billing/print/<int:bid>')
@login_required
def print_bill(bid):
    cur = mysql.connection.cursor()
    cur.execute("""SELECT b.*, p.first_name, p.last_name, p.phone, p.email, p.address,
                          a.appointment_date, a.appointment_time, a.reason, a.notes as doc_notes,
                          u.full_name as doctor_name, d.specialization
                   FROM billing b
                   JOIN patients p ON b.patient_id=p.id
                   LEFT JOIN appointments a ON b.appointment_id=a.id
                   LEFT JOIN doctors d ON a.doctor_id=d.id
                   LEFT JOIN users u ON d.user_id=u.id WHERE b.id=%s""", (bid,))
    bill = cur.fetchone()
    cur.close()
    if not bill:
        flash('Bill not found.', 'error')
        return redirect(url_for('billing'))
    return render_template('bill_print.html', bill=bill, today=date.today())

@app.route('/billing/print_safe/<int:bid>')
@login_required
def print_bill_safe(bid):
    """For discharged patients whose record is deleted — uses LEFT JOIN"""
    cur = mysql.connection.cursor()
    cur.execute("""SELECT b.*,
                          COALESCE(p.first_name,'[Discharged]') as first_name,
                          COALESCE(p.last_name,'') as last_name,
                          p.phone, p.email, p.address,
                          a.appointment_date, a.appointment_time, a.reason, a.notes as doc_notes,
                          u.full_name as doctor_name, d.specialization
                   FROM billing b
                   LEFT JOIN patients p ON b.patient_id=p.id
                   LEFT JOIN appointments a ON b.appointment_id=a.id
                   LEFT JOIN doctors d ON a.doctor_id=d.id
                   LEFT JOIN users u ON d.user_id=u.id WHERE b.id=%s""", (bid,))
    bill = cur.fetchone()
    cur.close()
    if not bill:
        flash('Bill not found.', 'error')
        return redirect(url_for('billing'))
    return render_template('bill_print.html', bill=bill, today=date.today())

# ─── Doctors ───────────────────────────────────────────────────────────────────
@app.route('/doctors')
@login_required
def doctors():
    cur = mysql.connection.cursor()
    cur.execute("SELECT d.*, u.full_name, u.email, u.username FROM doctors d JOIN users u ON d.user_id=u.id")
    doctors_list = cur.fetchall()
    cur.close()
    return render_template('doctors.html', doctors=doctors_list)

@app.route('/doctors/schedule/<int:did>')
@login_required
def doctor_schedule(did):
    cur = mysql.connection.cursor()
    cur.execute("SELECT d.*, u.full_name FROM doctors d JOIN users u ON d.user_id=u.id WHERE d.id=%s", (did,))
    doctor = cur.fetchone()
    cur.execute("""SELECT a.*, p.first_name, p.last_name FROM appointments a
                   JOIN patients p ON a.patient_id=p.id WHERE a.doctor_id=%s AND a.status='scheduled'
                   ORDER BY a.appointment_date, a.appointment_time""", (did,))
    schedule = cur.fetchall()
    cur.close()
    return render_template('doctor_schedule.html', doctor=doctor, schedule=schedule)

# ─── Appointments ──────────────────────────────────────────────────────────────
@app.route('/appointments')
@login_required
def appointments():
    cur = mysql.connection.cursor()
    if session.get('role') == 'doctor':
        cur.execute("SELECT d.id FROM doctors d JOIN users u ON d.user_id=u.id WHERE u.id=%s", (session['user_id'],))
        row = cur.fetchone()
        doc_id = row['id'] if row else 0
        cur.execute("""SELECT a.*, p.first_name, p.last_name, u.full_name as doctor_name, d.specialization
                       FROM appointments a JOIN patients p ON a.patient_id=p.id
                       JOIN doctors d ON a.doctor_id=d.id JOIN users u ON d.user_id=u.id
                       WHERE a.doctor_id=%s ORDER BY a.appointment_date DESC""", (doc_id,))
    else:
        cur.execute("""SELECT a.*, p.first_name, p.last_name, u.full_name as doctor_name, d.specialization
                       FROM appointments a JOIN patients p ON a.patient_id=p.id
                       JOIN doctors d ON a.doctor_id=d.id JOIN users u ON d.user_id=u.id
                       ORDER BY a.appointment_date DESC""")
    appts = cur.fetchall()
    cur.close()
    return render_template('appointments.html', appointments=appts)

@app.route('/appointments/add', methods=['GET', 'POST'])
@login_required
def add_appointment():
    cur = mysql.connection.cursor()
    if request.method == 'POST':
        cur.execute("""INSERT INTO appointments (patient_id,doctor_id,appointment_date,appointment_time,reason,status)
                       VALUES (%s,%s,%s,%s,%s,'scheduled')""",
                    (request.form['patient_id'], request.form['doctor_id'],
                     request.form['appointment_date'], request.form['appointment_time'], nv('reason')))
        mysql.connection.commit()
        cur.close()
        flash('Appointment scheduled!', 'success')
        return redirect(url_for('appointments'))
    cur.execute("SELECT id, first_name, last_name FROM patients ORDER BY first_name")
    patients_list = cur.fetchall()
    cur.execute("SELECT d.id, u.full_name, d.specialization FROM doctors d JOIN users u ON d.user_id=u.id")
    doctors_list = cur.fetchall()
    cur.close()
    return render_template('appointment_form.html', patients=patients_list, doctors=doctors_list)

@app.route('/appointments/update_status/<int:aid>', methods=['POST'])
@login_required
def update_appointment_status(aid):
    status = request.form.get('status')
    cur = mysql.connection.cursor()
    cur.execute("UPDATE appointments SET status=%s WHERE id=%s", (status, aid))
    mysql.connection.commit()
    cur.close()
    flash('Appointment status updated.', 'success')
    return redirect(url_for('appointments'))

@app.route('/appointments/delete/<int:aid>', methods=['POST'])
@receptionist_required
def delete_appointment(aid):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM appointments WHERE id=%s", (aid,))
    mysql.connection.commit()
    cur.close()
    flash('Appointment deleted.', 'success')
    return redirect(url_for('appointments'))

# ─── Billing ───────────────────────────────────────────────────────────────────
@app.route('/billing')
@login_required
def billing():
    cur = mysql.connection.cursor()
    cur.execute("""SELECT b.*, COALESCE(p.first_name,'[Discharged]') as first_name,
                          COALESCE(p.last_name,'') as last_name
                   FROM billing b LEFT JOIN patients p ON b.patient_id=p.id
                   ORDER BY b.billing_date DESC""")
    bills = cur.fetchall()
    cur.close()
    return render_template('billing.html', bills=bills)

@app.route('/billing/add', methods=['GET', 'POST'])
@receptionist_required
def add_billing():
    cur = mysql.connection.cursor()
    if request.method == 'POST':
        def sf(k, d=0.0):
            try: return float(request.form.get(k, d) or d)
            except: return d
        amount = sf('amount'); discount = sf('discount'); tax = sf('tax')
        total = round(amount - discount + tax, 2)
        cur.execute("""INSERT INTO billing (patient_id,appointment_id,description,amount,discount,tax,total,status,payment_method,billing_date)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (request.form['patient_id'], nv('appointment_id'),
                     request.form['description'].strip(),
                     amount, discount, tax, total,
                     request.form.get('status','pending'),
                     request.form.get('payment_method','cash'),
                     nv('billing_date') or date.today()))
        mysql.connection.commit()
        cur.close()
        flash('Bill created!', 'success')
        return redirect(url_for('billing'))
    cur.execute("SELECT id, first_name, last_name FROM patients ORDER BY first_name")
    patients_list = cur.fetchall()
    cur.execute("""SELECT a.id, p.first_name, p.last_name, a.appointment_date FROM appointments a
                   JOIN patients p ON a.patient_id=p.id ORDER BY a.appointment_date DESC""")
    appointments_list = cur.fetchall()
    cur.close()
    return render_template('billing_form.html', patients=patients_list, appointments=appointments_list)

@app.route('/billing/pay/<int:bid>', methods=['POST'])
@login_required
def mark_paid(bid):
    cur = mysql.connection.cursor()
    cur.execute("UPDATE billing SET status='paid', paid_date=CURDATE() WHERE id=%s", (bid,))
    mysql.connection.commit()
    cur.close()
    flash('Payment recorded.', 'success')
    return redirect(url_for('billing'))

@app.route('/billing/delete/<int:bid>', methods=['POST'])
@receptionist_required
def delete_billing(bid):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM billing WHERE id=%s", (bid,))
    mysql.connection.commit()
    cur.close()
    flash('Bill deleted.', 'success')
    return redirect(url_for('billing'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)

# ─── Queue System ──────────────────────────────────────────────────────────────

@app.route('/queue/accept/<int:aid>', methods=['POST'])
@doctor_required
def queue_accept(aid):
    """Doctor accepts the next patient — marks them as called/in_consultation"""
    cur = mysql.connection.cursor()
    # First set any current in_consultation back to waiting (only one at a time)
    cur.execute("""UPDATE appointments SET queue_status='waiting'
                   WHERE queue_status='in_consultation' AND appointment_date=CURDATE()""")
    # Call this patient in
    cur.execute("""UPDATE appointments SET queue_status='in_consultation', queue_called_at=NOW()
                   WHERE id=%s""", (aid,))
    mysql.connection.commit()
    cur.close()
    flash('Patient called in. They are now in consultation.', 'success')
    return redirect(url_for('appointments'))

@app.route('/queue/done/<int:aid>', methods=['POST'])
@doctor_required
def queue_done(aid):
    """Doctor marks consultation done — patient leaves queue"""
    cur = mysql.connection.cursor()
    cur.execute("UPDATE appointments SET queue_status='done' WHERE id=%s", (aid,))
    mysql.connection.commit()
    cur.close()
    flash('Patient consultation marked done.', 'success')
    return redirect(url_for('appointments'))

@app.route('/queue/enqueue/<int:aid>', methods=['POST'])
@receptionist_required
def queue_enqueue(aid):
    """Receptionist marks patient as arrived/waiting"""
    cur = mysql.connection.cursor()
    cur.execute("UPDATE appointments SET queue_status='waiting' WHERE id=%s", (aid,))
    mysql.connection.commit()
    cur.close()
    flash('Patient added to queue.', 'success')
    return redirect(url_for('appointments'))

@app.route('/api/queue')
@login_required
def api_queue():
    """JSON endpoint for live queue data — polled every 15s"""
    from flask import jsonify
    cur = mysql.connection.cursor()
    # Currently in consultation
    cur.execute("""SELECT a.id, p.first_name, p.last_name, u.full_name as doctor_name,
                          a.appointment_time, a.queue_status, a.queue_called_at
                   FROM appointments a JOIN patients p ON a.patient_id=p.id
                   JOIN doctors d ON a.doctor_id=d.id JOIN users u ON d.user_id=u.id
                   WHERE a.queue_status='in_consultation' AND a.appointment_date=CURDATE()
                   ORDER BY a.queue_called_at DESC LIMIT 1""")
    current = cur.fetchone()

    # Waiting queue (ordered by appointment time)
    cur.execute("""SELECT a.id, p.first_name, p.last_name, u.full_name as doctor_name,
                          a.appointment_time, a.queue_status
                   FROM appointments a JOIN patients p ON a.patient_id=p.id
                   JOIN doctors d ON a.doctor_id=d.id JOIN users u ON d.user_id=u.id
                   WHERE a.queue_status='waiting' AND a.appointment_date=CURDATE()
                   ORDER BY a.appointment_time ASC""")
    waiting = cur.fetchall()
    cur.close()

    def fmt(row):
        if not row: return None
        return {
            'id': row['id'],
            'name': f"{row['first_name']} {row['last_name']}",
            'doctor': row['doctor_name'],
            'time': str(row['appointment_time']),
            'status': row['queue_status']
        }

    return jsonify({
        'current': fmt(current),
        'waiting': [fmt(r) for r in waiting],
        'waiting_count': len(waiting)
    })
