import csv
import os
import sys
from flask import Flask, render_template, request, redirect, url_for, flash
from threading import Timer

# Configuração do GPIO
if sys.platform.startswith("win"):
    from dummy_gpio import GPIO  # Usa o simulador no Windows
else:
    import RPi.GPIO as GPIO  # Usa o GPIO real no Raspberry Pi

# Configuração do pino da porta
DOOR_PIN = 17
GPIO.setmode(GPIO.BCM)
GPIO.setup(DOOR_PIN, GPIO.OUT)
GPIO.output(DOOR_PIN, GPIO.LOW)

# Configuração do Flask
app = Flask(__name__)
app.secret_key = 'super_secret_key'

# Arquivos CSV
BOLSISTAS_CSV = 'bolsistas.csv'
VISITAS_CSV = 'visitas.csv'

# Funções para controle da porta
def abrir_porta():
    GPIO.output(DOOR_PIN, GPIO.HIGH)
    Timer(5, fechar_porta).start()

def fechar_porta():
    GPIO.output(DOOR_PIN, GPIO.LOW)

# Rota inicial (página de entrada)
@app.route('/')
def index():
    return render_template('index.html')

# Rota para a home (após clicar em iniciar)
@app.route('/home')
def home():
    return render_template('home.html')

# Rota para processar o botão iniciar
@app.route('/iniciar', methods=['POST'])
def iniciar():
    return redirect(url_for('home'))

# Rota para visitantes
@app.route('/visitante', methods=['GET', 'POST'])
def visitante():
    if request.method == 'POST':
        nome = request.form['nome']
        matricula = request.form['matricula']
        motivo = request.form['motivo']

        with open(VISITAS_CSV, 'a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([nome, matricula, motivo])

        if os.path.exists(BOLSISTAS_CSV) and os.path.getsize(BOLSISTAS_CSV) > 0:
            abrir_porta()
        
        return render_template('visitante_success.html', nome=nome)

    return render_template('visitante.html')

# Rota para bolsistas
@app.route('/bolsista', methods=['GET', 'POST'])
def bolsista():
    if request.method == 'POST':
        nome = request.form['nome']
        matricula = request.form['matricula']

        if os.path.exists(BOLSISTAS_CSV):
            with open(BOLSISTAS_CSV, 'r') as file:
                reader = csv.reader(file)
                for row in reader:
                    if row and row[0] == nome and row[1] == matricula:
                        abrir_porta()
                        return render_template('bolsista_success.html', nome=nome)

        return render_template('bolsista_fail.html')

    return render_template('bolsista.html')

# Rota para cadastrar bolsistas
@app.route('/cadastrar_bolsista', methods=['POST'])
def cadastrar_bolsista():
    nome = request.form['nome']
    matricula = request.form['matricula']

    with open(BOLSISTAS_CSV, 'a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([nome, matricula])

    flash('Bolsista cadastrado com sucesso!')
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')