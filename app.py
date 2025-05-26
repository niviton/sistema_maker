import csv
import os
import sys
import threading
import time
import json
import requests
import serial
from serial.tools import list_ports
from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
from functools import wraps

# ===== Detect available serial ports =====
ports = list_ports.comports()
print("Portas disponíveis:")
for p in ports:
    print(f"  {p.device} — {p.description}")

# ===== Configurações Básicas =====
app = Flask(__name__)
app.secret_key = 'super_secret_key'

@app.context_processor
def inject_is_admin():
    return {'is_admin': session.get('is_admin', False)}

# ===== Auto-detecta porta Serial =====
def auto_detect_serial():
    for p in list_ports.comports():
        desc = p.description.lower()
        if 'usb' in desc or 'cp210' in desc or 'ftdi' in desc:
            return p.device
    return None

SERIAL_PORT = auto_detect_serial() or ('COM3' if sys.platform.startswith("win") else '/dev/ttyUSB0')
BAUD_RATE = 115200
try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)
    app.logger.info(f"Serial aberta em {SERIAL_PORT}")
except Exception as e:
    ser = None
    app.logger.warning(f"[SERIAL] Falha ao abrir {SERIAL_PORT}: {e}")

# ===== GPIO Configuration =====
if sys.platform.startswith("win"):
    class GPIO:
        BCM = OUT = IN = HIGH = LOW = None
        @staticmethod
        def setmode(mode): pass
        @staticmethod
        def setup(pin, mode): pass
        @staticmethod
        def output(pin, value):
            print(f"[GPIO SIMULADO] pino {pin} -> {value}")
else:
    import RPi.GPIO as GPIO

DOOR_PIN = 17
GPIO.setmode(GPIO.BCM)
GPIO.setup(DOOR_PIN, GPIO.OUT)
GPIO.output(DOOR_PIN, GPIO.LOW)

# ===== ESP32 HTTP =====
ESP_IP = "192.168.0.53"
ESP_BASE_URL = f"http://{ESP_IP}"

def abrir_porta_esp():
    try:
        requests.get(f"{ESP_BASE_URL}/open", timeout=1)
        app.logger.info("Relé acionado via ESP32")
    except Exception as e:
        app.logger.error(f"Falha ao acionar relé via ESP32: {e}")

def controlar_led_esp(on: bool):
    try:
        state = "on" if on else "off"
        requests.get(f"{ESP_BASE_URL}/led", params={'state': state}, timeout=1)
        app.logger.info(f"LED set to {state} via ESP32")
    except Exception as e:
        app.logger.error(f"Falha ao controlar LED via ESP32: {e}")

# ===== Arquivos de dados =====
BOLSISTAS_CSV = 'bolsistas.csv'
VISITAS_CSV = 'visitas.csv'
PONTOS_CSV = 'pontos.csv'
ESTADO_LAB_TXT = 'estado_lab.txt'
SHEETS_BUFFER_JSON = 'sheets_buffer.json'

# ===== Google Sheets Integration =====
SHEETS_WEBAPP_URL = 'https://script.google.com/macros/s/AKfycbwXd3B25eg-DXrem3KZ0Yel3HavuHlS8X5gXAgtCdl6DklQiu2fS-R6W2YQaeF2Jjix/exec'
ADMIN_PASSWORD = 'maker22'

# ===== Inicialização de arquivos =====
for path in (VISITAS_CSV, BOLSISTAS_CSV):
    if not os.path.exists(path):
        open(path, 'w').close()

if not os.path.exists(PONTOS_CSV):
    with open(PONTOS_CSV, 'w', newline='') as f:
        csv.writer(f).writerow(['Nome', 'ID', 'Data', 'Entrada', 'Saída', 'Duraçao(min)'])

if not os.path.exists(ESTADO_LAB_TXT):
    with open(ESTADO_LAB_TXT, 'w') as f:
        f.write('FECHADO')

if not os.path.exists(SHEETS_BUFFER_JSON):
    with open(SHEETS_BUFFER_JSON, 'w') as f:
        json.dump([], f)

# ===== Estado do Lab =====
def get_estado_lab():
    return open(ESTADO_LAB_TXT).read().strip().upper()

def set_estado_lab(novo):
    with open(ESTADO_LAB_TXT, 'w') as f:
        f.write(novo.strip().upper())

# ===== Google Sheets Buffer =====
buffer_lock = threading.Lock()

def load_buffer():
    with buffer_lock, open(SHEETS_BUFFER_JSON, 'r') as f:
        return json.load(f)

def save_buffer(buf):
    with buffer_lock, open(SHEETS_BUFFER_JSON, 'w') as f:
        json.dump(buf, f)

def enqueue_sheets(params):
    buf = load_buffer()
    buf.append(params)
    save_buffer(buf)

def try_flush_buffer():
    buf = load_buffer()
    new_buf = []
    for params in buf:
        try:
            resp = requests.get(SHEETS_WEBAPP_URL, params=params, timeout=5)
            resp.raise_for_status()
            app.logger.info(f"[Sheets] enviado: {params}")
        except Exception as e:
            app.logger.warning(f"[Sheets] falha buffer para {params}: {e}")
            new_buf.append(params)
    if len(new_buf) != len(buf):
        save_buffer(new_buf)

def background_sheets_flusher():
    while True:
        try_flush_buffer()
        time.sleep(10)

threading.Thread(target=background_sheets_flusher, daemon=True).start()

# ===== Authentication =====
def login_required(f):
    @wraps(f)
    def dec(*args, **kw):
        if not session.get('is_admin'):
            return redirect(url_for('login'))
        return f(*args, **kw)
    return dec

# ===== Rotas =====
@app.route('/login', methods=('GET', 'POST'))
def login():
    if request.method == 'POST':
        if request.form.get('senha', '') == ADMIN_PASSWORD:
            session['is_admin'] = True
            flash('Login OK', 'success')
            return redirect(url_for('admin'))
        flash('Senha incorreta', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('is_admin', None)
    flash('Logout realizado', 'info')
    return redirect(url_for('home'))

@app.route('/')
def index():
    return render_template('index.html',
                           estado=get_estado_lab(),
                           is_admin=session.get('is_admin', False))

@app.route('/home')
def home():
    return render_template('home.html',
                           estado=get_estado_lab(),
                           is_admin=session.get('is_admin', False))

@app.route('/visitante', methods=('GET', 'POST'))
def visitante():
    estado = get_estado_lab()
    if request.method == 'POST':
        if estado != 'ABERTO':
            flash('Lab fechado', 'danger')
            return render_template('visitante.html', estado=estado)
        nome = request.form['nome']
        matricula = request.form['matricula']
        motivo = request.form['motivo']
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(VISITAS_CSV, 'a', newline='') as f:
            csv.writer(f).writerow([nome, matricula, motivo, ts])
        abrir_porta_esp()
        controlar_led_esp(True)
        threading.Timer(5, lambda: controlar_led_esp(False)).start()
        flash('Visitante registrado!', 'success')
        enqueue_sheets({
            'nome': nome, 'id': matricula,
            'acao': 'VISITA', 'motivo': motivo, 'datahora': ts
        })
        return render_template('visitante_success.html',
                               nome=nome, estado=estado, acesso=True)
    return render_template('visitante.html', estado=estado)

@app.route('/bolsista', methods=('GET', 'POST'))
def bolsista():
    if request.method == 'POST':
        nome = request.form['nome']
        matricula = request.form['matricula']
        validado = False
        with open(BOLSISTAS_CSV) as f:
            for row in csv.reader(f):
                if row and row[0] == nome and row[1] == matricula:
                    validado = True
                    break
        if not validado:
            flash('Não cadastrado', 'danger')
            return render_template('bolsista_fail.html')
        
        abrir_porta_esp()
        controlar_led_esp(True)
        threading.Timer(5, lambda: controlar_led_esp(False)).start()
        flash('Bolsista validado!', 'success')
        enqueue_sheets({
            'nome': nome,
            'id': matricula,
            'acao': 'PONTO',
            'datahora': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        return redirect(url_for('bolsista_success',
                               nome=nome,
                               matricula=matricula,
                               estado=get_estado_lab()))
    return render_template('bolsista.html')

@app.route('/bolsista_success')
def bolsista_success():
    return render_template('bolsista_success.html',
                           nome=request.args.get('nome'),
                           matricula=request.args.get('matricula'),
                           estado=request.args.get('estado'))

@app.route('/marcar_ponto', methods=('POST',))
def marcar_ponto():
    nome = request.form['nome']
    matricula = request.form['matricula']
    acao = request.form['acao']
    now = datetime.now()
    dstr = now.strftime('%Y-%m-%d')
    tstr = now.strftime('%H:%M:%S')
    rows = list(csv.reader(open(PONTOS_CSV, 'r', newline='')))
    if acao == 'entrada':
        rows.append([nome, matricula, dstr, tstr, '', ''])
        flash(f'Entrada: {dstr} {tstr}', 'success')
    else:
        updated = False
        for i in range(len(rows)-1, 0, -1):
            r = rows[i]
            if r[0] == nome and r[1] == matricula and r[4] == '':
                ent = datetime.strptime(f"{r[2]} {r[3]}", '%Y-%m-%d %H:%M:%S')
                dur = round((now - ent).total_seconds()/60, 2)
                r[4] = tstr
                r[5] = str(dur)
                flash(f'Saída: {dstr} {tstr} ({dur}min)', 'success')
                updated = True
                break
        if not updated:
            flash('Nenhuma entrada pendente', 'danger')
    with open(PONTOS_CSV, 'w', newline='') as f:
        csv.writer(f).writerows(rows)
    enqueue_sheets({
        'nome': nome, 'id': matricula,
        'acao': acao.upper(), 'data': dstr, 'hora': tstr
    })
    return render_template('bolsista_success.html',
                           nome=nome, matricula=matricula,
                           estado=get_estado_lab())

@app.route('/admin')
@login_required
def admin():
    return render_template('admin.html')

@app.route('/cadastrar_bolsista', methods=('POST',))
@login_required
def cadastrar_bolsista():
    n = request.form['nome']
    m = request.form['matricula']
    with open(BOLSISTAS_CSV, 'a', newline='') as f:
        csv.writer(f).writerow([n, m])
    flash('Bolsista adicionado', 'success')
    return redirect(url_for('admin'))

@app.route('/remover_bolsista', methods=('POST',))
@login_required
def remover_bolsista():
    chave = request.form['chave'].strip()
    rows = []
    rem = False
    with open(BOLSISTAS_CSV) as f:
        for r in csv.reader(f):
            if r and (r[0] != chave and r[1] != chave):
                rows.append(r)
            else:
                rem = True
    with open(BOLSISTAS_CSV, 'w', newline='') as f:
        csv.writer(f).writerows(rows)
    flash('Removido' if rem else 'Não encontrado',
          'success' if rem else 'danger')
    return redirect(url_for('admin'))

@app.route('/atualizar_estado', methods=('POST',))
def atualizar_estado():
    novo = request.form.get('estado')
    if novo:
        set_estado_lab(novo)
        flash(f'Estado atualizado: {novo}', 'info')
    else:
        flash('Nada alterado', 'warning')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
