import csv
import os
import sys
import threading
import time
import serial           # pip install pyserial
from serial.tools import list_ports
from urllib.parse import urlencode
from urllib.request import urlopen
from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
from functools import wraps
#set USB_SERIAL_PORT=COM4
#python app.py


# ===== Configurações Básicas =====
app = Flask(__name__)
app.secret_key = 'super_secret_key'

@app.context_processor
def inject_is_admin():
    return {'is_admin': session.get('is_admin', False)}

# ===== Serial & Reconexão Automática =====
# Porta pode ser fixada via variável de ambiente USB_SERIAL_PORT
SERIAL_PORT = os.getenv('USB_SERIAL_PORT') or (
    'COM3' if sys.platform.startswith("win") else '/dev/ttyUSB0'
)
BAUD_RATE = 115200
ser = None

def try_open_serial():
    global ser
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        time.sleep(2)
        app.logger.info(f"[SERIAL] Aberta em {SERIAL_PORT}")
    except Exception as e:
        ser = None
        app.logger.warning(f"[SERIAL] Falha ao abrir {SERIAL_PORT}: {e}")

# Primeira tentativa
try_open_serial()

# Thread para reconectar a cada 10s
def serial_reconnector():
    while True:
        if ser is None or not ser.is_open:
            try_open_serial()
        time.sleep(10)

threading.Thread(target=serial_reconnector, daemon=True).start()

# ===== GPIO simulado (Windows) ou real no Raspberry =====
if sys.platform.startswith("win"):
    class GPIO:
        BCM = OUT = HIGH = LOW = None
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

# ===== Arquivos de dados =====
BOLSISTAS_CSV = 'bolsistas.csv'
VISITAS_CSV    = 'visitas.csv'
PONTOS_CSV     = 'pontos.csv'
ESTADO_LAB_TXT = 'estado_lab.txt'
SHEETS_WEBAPP_URL = (
    'https://script.google.com/macros/s/AKfycbwXd3B25eg-DXrem3KZ0Yel3HavuHlS8X5gXAgtCdl6DklQiu2fS-R6W2YQaeF2Jjix/exec'
)
ADMIN_PASSWORD = 'maker22'

# Inicialização de arquivos
if not os.path.exists(ESTADO_LAB_TXT):
    with open(ESTADO_LAB_TXT, 'w') as f:
        f.write('FECHADO')
if not os.path.exists(PONTOS_CSV):
    with open(PONTOS_CSV, 'w', newline='') as f:
        csv.writer(f).writerow(['Nome','ID','Data','Entrada','Saída','Duração(min)'])
if not os.path.exists(VISITAS_CSV):
    open(VISITAS_CSV, 'w').close()
if not os.path.exists(BOLSISTAS_CSV):
    open(BOLSISTAS_CSV, 'w').close()

# ===== Funções de controle =====
def control_led(turn_on: bool):
    if ser and ser.is_open:
        cmd = b'LED_ON\n' if turn_on else b'LED_OFF\n'
        try:
            ser.write(cmd)
            app.logger.info(f"[SERIAL] {'LED_ON' if turn_on else 'LED_OFF'} enviado")
        except Exception as e:
            app.logger.error(f"[SERIAL] Erro LED: {e}")
    else:
        app.logger.warning("[SERIAL] LED não disponível, pulso GPIO alternativo")

def abrir_porta(pulse_ms: int = 100):
    # Tenta via ESP32
    if ser and ser.is_open:
        try:
            ser.write(b'OPEN\n')
            app.logger.info("[SERIAL] OPEN enviado")
        except Exception as e:
            app.logger.error(f"[SERIAL] Erro OPEN: {e}")
    else:
        # Fallback GPIO
        def _pulse_gpio():
            GPIO.output(DOOR_PIN, GPIO.HIGH)
            time.sleep(pulse_ms / 1000)
            GPIO.output(DOOR_PIN, GPIO.LOW)
        threading.Thread(target=_pulse_gpio, daemon=True).start()
        app.logger.info("[GPIO] Fallback pulso aplicado")
    # Pisca LED
    control_led(True)
    threading.Timer(pulse_ms / 1000, lambda: control_led(False)).start()

def get_estado_lab():
    return open(ESTADO_LAB_TXT).read().strip().upper()

def set_estado_lab(n):
    with open(ESTADO_LAB_TXT,'w') as f:
        f.write(n.strip().upper())

def _send_to_sheets(params):
    url = f"{SHEETS_WEBAPP_URL}?{urlencode(params)}"
    try:
        with urlopen(url, timeout=5) as resp:
            app.logger.info(f"[SHEETS] {resp.read().decode()}")
    except Exception as e:
        app.logger.error(f"[SHEETS] Erro: {e}")

def enviar_para_sheets(params):
    threading.Thread(target=_send_to_sheets, args=(params,), daemon=True).start()

# ===== Decorator =====
def login_required(f):
    @wraps(f)
    def deco(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return deco

# ===== Rotas =====
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        if request.form.get('senha','') == ADMIN_PASSWORD:
            session['is_admin'] = True
            flash('Login bem-sucedido!', 'success')
            return redirect(url_for('admin'))
        flash('Senha incorreta.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('is_admin', None)
    flash('Você saiu do painel de administração.', 'info')
    return redirect(url_for('home'))

@app.route('/')
def index():
    return redirect(url_for('home'))

@app.route('/home')
def home():
    return render_template('home.html',
                           estado=get_estado_lab(),
                           is_admin=session.get('is_admin', False))

@app.route('/iniciar', methods=['POST'])
def iniciar():
    return redirect(url_for('home'))

@app.route('/visitante', methods=['GET','POST'])
def visitante():
    estado = get_estado_lab()
    if request.method == 'POST':
        if estado != 'ABERTO':
            flash('Laboratório não está aberto para entrada.', 'danger')
            return render_template('visitante.html', estado=estado)
        nome      = request.form['nome']
        matricula = request.form['matricula']
        motivo    = request.form['motivo']
        ts        = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # grava local
        with open(VISITAS_CSV,'a', newline='') as f:
            csv.writer(f).writerow([nome, matricula, motivo, ts])
        # aciona
        acesso = os.path.getsize(BOLSISTAS_CSV)>0
        if acesso:
            abrir_porta(100)
            flash('Registro de visitante realizado, relé e LED acionados!', 'success')
        else:
            flash('Registro realizado, mas porta não aberta.', 'info')
        # envia sheets
        enviar_para_sheets({
            'nome': nome, 'id': matricula,
            'motivo': motivo, 'acao': 'VISITA',
            'datahora': ts
        })
        return render_template('visitante_success.html',
                               nome=nome, estado=estado, acesso=acesso)
    return render_template('visitante.html', estado=estado)

@app.route('/bolsista', methods=['GET','POST'])
def bolsista():
    if request.method == 'POST':
        nome      = request.form['nome']
        matricula = request.form['matricula']
        validado  = False
        with open(BOLSISTAS_CSV) as f:
            for row in csv.reader(f):
                if row and row[0]==nome and row[1]==matricula:
                    validado = True; break
        if not validado:
            flash('Bolsista não cadastrado.', 'danger')
            return render_template('bolsista_fail.html')
        abrir_porta(100)
        flash('Bolsista validado. Porta e LED acionados!', 'success')
        return render_template('bolsista_success.html',
                               nome=nome, matricula=matricula,
                               estado=get_estado_lab())
    return render_template('bolsista.html')

@app.route('/marcar_ponto', methods=['POST'])
def marcar_ponto():
    nome      = request.form['nome']
    matricula = request.form['matricula']
    acao      = request.form['acao']
    now       = datetime.now()
    date_str  = now.strftime('%Y-%m-%d')
    time_str  = now.strftime('%H:%M:%S')
    rows = list(csv.reader(open(PONTOS_CSV,'r', newline='')))
    if acao == 'entrada':
        rows.append([nome, matricula, date_str, time_str, '', ''])
        flash(f'Ponto de Entrada: {date_str}, {time_str}', 'success')
    else:
        updated=False
        for i in range(len(rows)-1,0,-1):
            r=rows[i]
            if r[0]==nome and r[1]==matricula and r[4]=='':
                ent_dt = datetime.strptime(f"{r[2]} {r[3]}", '%Y-%m-%d %H:%M:%S')
                dur_min = round((now-ent_dt).total_seconds()/60,2)
                r[4],r[5]=time_str,str(dur_min)
                flash(f'Ponto de Saída: {date_str}, {time_str} ({dur_min} min)', 'success')
                updated=True; break
        if not updated:
            flash('Nenhuma entrada pendente encontrada.', 'danger')
    with open(PONTOS_CSV,'w', newline='') as f:
        csv.writer(f).writerows(rows)
    enviar_para_sheets({'id': matricula,'nome': nome,'acao': acao.upper(),'data': date_str,'hora': time_str})
    return render_template('bolsista_success.html',
                           nome=nome, matricula=matricula,
                           estado=get_estado_lab())

@app.route('/admin')
@login_required
def admin():
    return render_template('admin.html')

@app.route('/cadastrar_bolsista', methods=['POST'])
@login_required
def cadastrar_bolsista():
    with open(BOLSISTAS_CSV,'a', newline='') as f:
        csv.writer(f).writerow([request.form['nome'], request.form['matricula']])
    flash('Bolsista cadastrado com sucesso!', 'success')
    return redirect(url_for('admin'))

@app.route('/remover_bolsista', methods=['POST'])
@login_required
def remover_bolsista():
    chave = request.form['chave'].strip()
    rows, rem = [], False
    for r in csv.reader(open(BOLSISTAS_CSV,'r', newline='')):
        if r and (r[0]!=chave and r[1]!=chave):
            rows.append(r)
        else:
            rem = True
    with open(BOLSISTAS_CSV,'w', newline='') as f:
        csv.writer(f).writerows(rows)
    flash(rem and 'Bolsista removido!' or 'Bolsista não encontrado.',
          rem and 'success' or 'danger')
    return redirect(url_for('admin'))

@app.route('/atualizar_estado', methods=['POST'])
def atualizar_estado():
    novo = request.form.get('estado')
    if novo:
        set_estado_lab(novo)
        flash(f"Estado do laboratório atualizado para: {novo}", 'info')
    else:
        flash('Nenhum estado fornecido.', 'warning')
    return redirect(url_for('home'))

# ===== Executar =====
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', use_reloader=False)
