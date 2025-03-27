import csv
import os
from flask import Flask, render_template, request, redirect, url_for, flash
import RPi.GPIO as GPIO

# Configuração do GPIO para o controle da porta (exemplo: pino 17)
DOOR_PIN = 26

GPIO.setmode(GPIO.BCM)
GPIO.setup(DOOR_PIN, GPIO.OUT)
GPIO.output(DOOR_PIN, GPIO.LOW)

app = Flask(__name__)
app.secret_key = "sua_chave_secreta"  # Substitua por uma chave segura

# Arquivos CSV
BOLSISTAS_CSV = "bolsistas.csv"   # Para cadastro de bolsistas
VISITAS_CSV = "visitas.csv"       # Para registros de visitantes

# Cria os arquivos CSV caso não existam
if not os.path.exists(BOLSISTAS_CSV):
    with open(BOLSISTAS_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["nome", "matricula"])  # Cabeçalho

if not os.path.exists(VISITAS_CSV):
    with open(VISITAS_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["nome", "matricula", "motivo"])  # Cabeçalho

# Rota: Tela Inicial – escolha entre Visitante e Bolsista
@app.route("/")
def home():
    return render_template("home.html")

# Rota para visitantes
@app.route("/visitante", methods=["GET", "POST"])
def visitante():
    if request.method == "POST":
        nome = request.form["nome"]
        matricula = request.form["matricula"]
        motivo = request.form["motivo"]

        # Registra o visitante no CSV
        with open(VISITAS_CSV, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([nome, matricula, motivo])

        # Se houver pelo menos um bolsista cadastrado, abre a porta automaticamente
        open_door = False
        with open(BOLSISTAS_CSV, "r") as f:
            reader = csv.reader(f)
            next(reader, None)  # Pula o cabeçalho
            for _ in reader:
                open_door = True
                break

        if open_door:
            GPIO.output(DOOR_PIN, GPIO.HIGH)
            flash("Porta aberta automaticamente, pois há bolsista cadastrado!", "success")
        else:
            flash("Registro realizado. Aguarde instruções para abertura da porta.", "info")

        return render_template("visitante_success.html", nome=nome)
    return render_template("visitante.html")

# Rota para bolsistas
@app.route("/bolsista", methods=["GET", "POST"])
def bolsista():
    if request.method == "POST":
        nome = request.form["nome"]
        matricula = request.form["matricula"]

        # Valida se o bolsista está cadastrado
        found = False
        with open(BOLSISTAS_CSV, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["nome"].strip().lower() == nome.strip().lower() and row["matricula"].strip() == matricula.strip():
                    found = True
                    break

        if found:
            GPIO.output(DOOR_PIN, GPIO.HIGH)
            flash("Bolsista validado. Porta aberta!", "success")
            return render_template("bolsista_success.html", nome=nome)
        else:
            flash("Bolsista não cadastrado. Acesso negado.", "danger")
            return render_template("bolsista_fail.html", nome=nome)
    return render_template("bolsista.html")

# Rota opcional para fechar a porta
@app.route("/fechar")
def fechar():
    GPIO.output(DOOR_PIN, GPIO.LOW)
    flash("Porta fechada.", "info")
    return redirect(url_for("home"))

if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", port=5000, debug=True)
    finally:
        GPIO.cleanup()
