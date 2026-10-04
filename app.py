from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import date
import mysql.connector

app = Flask(__name__)
app.secret_key = "hospitalSecretKey"

dbConfig = {"host": "localhost", "user": "root", "password": "root123", "use_pure": True}
dbName = "hospitalDb"
bloodGroups = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]


def getConnection(withDb=True):
    config = dict(dbConfig)
    if withDb:
        config["database"] = dbName
    return mysql.connector.connect(**config)


def setupDatabase():
    conn = getConnection(False)
    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS {dbName}")
    cur.execute(f"USE {dbName}")
    cur.execute("""CREATE TABLE IF NOT EXISTS patients (
        patientId INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(50) NOT NULL, age INT, gender VARCHAR(10), phone VARCHAR(15),
        address VARCHAR(100), bloodGroup VARCHAR(5), regDate DATE)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS doctors (
        doctorId INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(50) NOT NULL, specialisation VARCHAR(50), phone VARCHAR(15), fee DECIMAL(8,2))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS appointments (
        apptId INT AUTO_INCREMENT PRIMARY KEY,
        patientId INT, doctorId INT, apptDate DATE, apptTime TIME,
        status VARCHAR(15) DEFAULT 'Scheduled',
        FOREIGN KEY (patientId) REFERENCES patients(patientId) ON DELETE CASCADE,
        FOREIGN KEY (doctorId) REFERENCES doctors(doctorId) ON DELETE CASCADE)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS bills (
        billId INT AUTO_INCREMENT PRIMARY KEY,
        apptId INT, patientId INT, consultationFee DECIMAL(8,2), medicineCharges DECIMAL(8,2),
        roomCharges DECIMAL(8,2), total DECIMAL(10,2), billDate DATE,
        FOREIGN KEY (apptId) REFERENCES appointments(apptId) ON DELETE CASCADE,
        FOREIGN KEY (patientId) REFERENCES patients(patientId) ON DELETE CASCADE)""")
    conn.commit()
    cur.close()
    conn.close()


def runQuery(query, params=(), fetch=None):
    conn = getConnection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(query, params)
        if fetch == "all":
            return cur.fetchall()
        if fetch == "one":
            return cur.fetchone()
        conn.commit()
        return cur.lastrowid
    except mysql.connector.Error as err:
        flash(f"Database error: {err}")
        return [] if fetch == "all" else None
    finally:
        cur.close()
        conn.close()


@app.route("/")
def dashboard():
    stats = {
        "patients": runQuery("SELECT COUNT(*) AS total FROM patients", fetch="one")["total"],
        "doctors": runQuery("SELECT COUNT(*) AS total FROM doctors", fetch="one")["total"],
        "scheduled": runQuery("SELECT COUNT(*) AS total FROM appointments WHERE status = 'Scheduled'", fetch="one")["total"],
        "revenue": runQuery("SELECT IFNULL(SUM(total), 0) AS total FROM bills", fetch="one")["total"]
    }
    doctorLoad = runQuery("""SELECT d.name, d.specialisation, COUNT(a.apptId) AS apptCount
        FROM doctors d LEFT JOIN appointments a ON d.doctorId = a.doctorId
        GROUP BY d.doctorId, d.name, d.specialisation ORDER BY apptCount DESC""", fetch="all")
    todayAppts = runQuery("""SELECT a.apptTime, a.status, p.name AS patientName, d.name AS doctorName
        FROM appointments a JOIN patients p ON a.patientId = p.patientId
        JOIN doctors d ON a.doctorId = d.doctorId
        WHERE a.apptDate = CURDATE() ORDER BY a.apptTime""", fetch="all")
    return render_template("dashboard.html", stats=stats, doctorLoad=doctorLoad, todayAppts=todayAppts)


@app.route("/patients", methods=["GET", "POST"])
def patients():
    if request.method == "POST":
        formData = request.form
        runQuery("""INSERT INTO patients (name, age, gender, phone, address, bloodGroup, regDate)
            VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                 (formData["name"], formData["age"], formData["gender"], formData["phone"],
                  formData["address"], formData["bloodGroup"], date.today()))
        flash(f"Patient {formData['name']} added.")
        return redirect(url_for("patients"))
    searchText = request.args.get("search", "")
    patientList = runQuery("SELECT * FROM patients WHERE name LIKE %s ORDER BY patientId DESC",
                           (f"%{searchText}%",), fetch="all")
    return render_template("patients.html", patientList=patientList, searchText=searchText, bloodGroups=bloodGroups)


@app.route("/patients/edit/<int:patientId>", methods=["GET", "POST"])
def editPatient(patientId):
    if request.method == "POST":
        formData = request.form
        runQuery("""UPDATE patients SET name = %s, age = %s, gender = %s, phone = %s, address = %s, bloodGroup = %s
            WHERE patientId = %s""",
                 (formData["name"], formData["age"], formData["gender"], formData["phone"],
                  formData["address"], formData["bloodGroup"], patientId))
        flash("Patient details updated.")
        return redirect(url_for("patients"))
    patient = runQuery("SELECT * FROM patients WHERE patientId = %s", (patientId,), fetch="one")
    if not patient:
        flash("Patient not found.")
        return redirect(url_for("patients"))
    return render_template("editPatient.html", p=patient, bloodGroups=bloodGroups)


@app.route("/patients/delete/<int:patientId>")
def deletePatient(patientId):
    runQuery("DELETE FROM patients WHERE patientId = %s", (patientId,))
    flash("Patient deleted.")
    return redirect(url_for("patients"))


@app.route("/doctors", methods=["GET", "POST"])
def doctors():
    if request.method == "POST":
        formData = request.form
        runQuery("INSERT INTO doctors (name, specialisation, phone, fee) VALUES (%s, %s, %s, %s)",
                 (formData["name"], formData["specialisation"], formData["phone"], formData["fee"]))
        flash(f"Dr. {formData['name']} added.")
        return redirect(url_for("doctors"))
    selectedSpec = request.args.get("specialisation", "")
    specList = runQuery("SELECT DISTINCT specialisation FROM doctors ORDER BY specialisation", fetch="all")
    if selectedSpec:
        doctorList = runQuery("SELECT * FROM doctors WHERE specialisation = %s ORDER BY name", (selectedSpec,), fetch="all")
    else:
        doctorList = runQuery("SELECT * FROM doctors ORDER BY name", fetch="all")
    return render_template("doctors.html", doctorList=doctorList, specList=specList, selectedSpec=selectedSpec)


@app.route("/doctors/delete/<int:doctorId>")
def deleteDoctor(doctorId):
    runQuery("DELETE FROM doctors WHERE doctorId = %s", (doctorId,))
    flash("Doctor deleted.")
    return redirect(url_for("doctors"))


@app.route("/appointments", methods=["GET", "POST"])
def appointments():
    if request.method == "POST":
        formData = request.form
        clash = runQuery("""SELECT apptId FROM appointments WHERE doctorId = %s AND apptDate = %s
            AND apptTime = %s AND status = 'Scheduled'""",
                         (formData["doctorId"], formData["apptDate"], formData["apptTime"]), fetch="one")
        if clash:
            flash("That doctor already has an appointment at this time. Pick another slot.")
        else:
            runQuery("INSERT INTO appointments (patientId, doctorId, apptDate, apptTime) VALUES (%s, %s, %s, %s)",
                     (formData["patientId"], formData["doctorId"], formData["apptDate"], formData["apptTime"]))
            flash("Appointment booked.")
        return redirect(url_for("appointments"))
    patientList = runQuery("SELECT patientId, name FROM patients ORDER BY name", fetch="all")
    doctorList = runQuery("SELECT doctorId, name, specialisation FROM doctors ORDER BY name", fetch="all")
    apptList = runQuery("""SELECT a.apptId, a.apptDate, a.apptTime, a.status,
        p.name AS patientName, d.name AS doctorName, d.specialisation
        FROM appointments a JOIN patients p ON a.patientId = p.patientId
        JOIN doctors d ON a.doctorId = d.doctorId
        ORDER BY a.apptDate DESC, a.apptTime DESC""", fetch="all")
    return render_template("appointments.html", patientList=patientList, doctorList=doctorList,
                      apptList=apptList, today=date.today().isoformat())


@app.route("/appointments/status/<int:apptId>/<newStatus>")
def updateStatus(apptId, newStatus):
    if newStatus in ("Completed", "Cancelled"):
        runQuery("UPDATE appointments SET status = %s WHERE apptId = %s", (newStatus, apptId))
        flash(f"Appointment #{apptId} marked {newStatus.lower()}.")
    return redirect(url_for("appointments"))


@app.route("/appointments/delete/<int:apptId>")
def deleteAppointment(apptId):
    runQuery("DELETE FROM appointments WHERE apptId = %s", (apptId,))
    flash("Appointment deleted.")
    return redirect(url_for("appointments"))


@app.route("/bills", methods=["GET", "POST"])
def bills():
    if request.method == "POST":
        apptId = request.form["apptId"]
        appt = runQuery("""SELECT a.patientId, d.fee FROM appointments a
            JOIN doctors d ON a.doctorId = d.doctorId WHERE a.apptId = %s""", (apptId,), fetch="one")
        if appt:
            medicineCharges = float(request.form["medicineCharges"] or 0)
            roomCharges = float(request.form["roomCharges"] or 0)
            consultationFee = float(appt["fee"])
            total = consultationFee + medicineCharges + roomCharges
            billId = runQuery("""INSERT INTO bills (apptId, patientId, consultationFee, medicineCharges, roomCharges, total, billDate)
                VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                              (apptId, appt["patientId"], consultationFee, medicineCharges, roomCharges, total, date.today()))
            if not billId:
                newBill = runQuery("SELECT MAX(billId) AS lastId FROM bills WHERE apptId = %s", (apptId,), fetch="one")
                billId = newBill["lastId"] if newBill else None
                if not billId:
                    flash("Could not generate the bill. Check the error above and try again.")
                    return redirect(url_for("bills"))
            flash(f"Bill #{billId} generated for Rs {total:.2f}.")
            return redirect(url_for("viewBill", billId=billId))
        flash("Appointment not found.")
        return redirect(url_for("bills"))
    unbilled = runQuery("""SELECT a.apptId, a.apptDate, p.name AS patientName, d.name AS doctorName, d.fee
        FROM appointments a JOIN patients p ON a.patientId = p.patientId
        JOIN doctors d ON a.doctorId = d.doctorId
        LEFT JOIN bills b ON a.apptId = b.apptId
        WHERE a.status = 'Completed' AND b.billId IS NULL ORDER BY a.apptDate""", fetch="all")
    billList = runQuery("""SELECT b.billId, b.billDate, b.total, p.name AS patientName
        FROM bills b JOIN patients p ON b.patientId = p.patientId ORDER BY b.billId DESC""", fetch="all")
    return render_template("bills.html", unbilled=unbilled, billList=billList)


@app.route("/bills/<int:billId>")
def viewBill(billId):
    bill = runQuery("""SELECT b.*, p.name AS patientName, p.age, p.gender, p.phone,
        d.name AS doctorName, d.specialisation, a.apptDate
        FROM bills b JOIN patients p ON b.patientId = p.patientId
        JOIN appointments a ON b.apptId = a.apptId
        JOIN doctors d ON a.doctorId = d.doctorId WHERE b.billId = %s""", (billId,), fetch="one")
    if not bill:
        flash("Bill not found.")
        return redirect(url_for("bills"))
    return render_template("viewBill.html", b=bill)


if __name__ == "__main__":
    setupDatabase()
    app.run(debug=True)
