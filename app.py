import csv
import os
import sys
import threading
import time
import serial  # pip install pyserial
from serial.tools import list_ports
from urllib.parse import urlencode
from urllib.request import urlopen
from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
from functools import wraps

# ===== Detect available serial ports and auto-detect ESP32 =====
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

# ===== Auto-detecta porta Serial do ESP32 =====
def auto_detect_serial():
    ports = list_ports.comports()
    for p in ports:
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
    app.logger.warning(f"Falha ao abrir serial {SERIAL_PORT}: {e}")

# ===== GPIO simulado (Windows) ou real no Raspberry =====
if sys.platform.startswith("win"):
    class GPIO:
        BCM = OUT = IN = HIGH = LOW = None
        @staticmethod
        def setmode(mode): pass
        @staticmethod
        def setup(pin, mode): pass
        @staticmethod
        def output(pin, value): print(f"[GPIO SIMULADO] pino {pin} -> {value}")
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

# ===== URL do Google Sheets Web App =====
SHEETS_WEBAPP_URL = (
    'https://script.google.com/macros/s/AKfycbwXd3B25eg-DXrem3KZ0Yel3HavuHlS8X5gXAgtCdl6DklQiu2fS-R6W2YQaeF2Jjix/exec'
)

# ===== Senha de acesso ao Admin =====
ADMIN_PASSWORD = 'maker22'

# ===== Inicialização de arquivos =====
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
            app.logger.info(f"Enviado comando {'LED_ON' if turn_on else 'LED_OFF'}")
        except Exception as e:
            app.logger.error(f"Erro ao escrever na serial para LED: {e}")
    else:
        app.logger.warning("Serial não disponível para controlar LED")


def abrir_porta(pulse_ms: int = 100):
    # Tenta acionar relé via ESP32
    if ser and ser.is_open:
        try:
            ser.write(b'OPEN\n')
            app.logger.info("Enviado comando OPEN ao ESP32")
        except Exception as e:
            app.logger.error(f"Erro ao escrever na serial para relé: {e}")
    else:
        # Fallback para GPIO local
        def _pulse_gpio():
            GPIO.output(DOOR_PIN, GPIO.HIGH)
            time.sleep(pulse_ms / 1000.0)
            GPIO.output(DOOR_PIN, GPIO.LOW)
        threading.Thread(target=_pulse_gpio, daemon=True).start()
        app.logger.info("Fallback GPIO pulse aplicado")
    # Pisca LED
    control_led(True)
    threading.Timer(pulse_ms/1000.0, lambda: control_led(False)).start()

# ===== Helper: estado do laboratório =====
def get_estado_lab():
    return open(ESTADO_LAB_TXT).read().strip().upper()

def set_estado_lab(novo):
    with open(ESTADO_LAB_TXT, 'w') as f:
        f.write(novo.strip().upper())

# ===== Helper: enviar dados ao Google Sheets (background) =====
def _send_to_sheets(params):
    qs = urlencode(params)
    url = f"{SHEETS_WEBAPP_URL}?{qs}"
    try:
        with urlopen(url, timeout=5) as resp:
            app.logger.info(f"Sheets respondeu: {resp.read().decode()}")
    except Exception as e:
        app.logger.error(f"Erro enviando ao Sheets: {e}")


def enviar_para_sheets(params):
    threading.Thread(target=_send_to_sheets, args=(params,), daemon=True).start()

# ===== Decorator para proteger rotas =====
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ===== Rotas de Autenticação =====
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        senha = request.form.get('senha','')
        if senha == ADMIN_PASSWORD:
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

# ===== Rotas Públicas =====
@app.route('/')
def index():
    return render_template('index.html', estado=get_estado_lab(), is_admin=session.get('is_admin', False))

@app.route('/home')
def home():
    return render_template('home.html', estado=get_estado_lab(), is_admin=session.get('is_admin', False))

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

        # 1) grava localmente
        with open(VISITAS_CSV,'a', newline='') as f:
            csv.writer(f).writerow([nome, matricula, motivo, ts])

        # 2) aciona porta e LED
        acesso = os.path.exists(BOLSISTAS_CSV) and os.path.getsize(BOLSISTAS_CSV)>0
        if acesso:
            abrir_porta(100)
            flash('Registro de visitante realizado, relé e LED acionados!', 'success')
        else:
            flash('Registro de visitante realizado, mas porta não aberta.', 'info')

        # 3) Monta parâmetros extras para empréstimo ou visita técnica
        params = {'nome': nome, 'id': matricula, 'motivo': motivo, 'acao': 'VISITA', 'datahora': ts}
        if motivo == 'Empréstimo':
            params['telefone'] = request.form.get('telefone','').strip()
        if motivo == 'Visita Técnica':
            params.update({
                'tipoInstituicao':  request.form.get('tipo_instituicao','').strip(),
                'nomeInstituicao':  request.form.get('nome_instituicao','').strip(),
                'numeroVisitantes': request.form.get('num_visitantes','').strip(),
                'objetivoVisita':   request.form.get('objetivo_visita','').strip()
            })
        
        # 4) envia ao Sheets em background
        enviar_para_sheets(params)

        # 5) responde rápido ao cliente
        return render_template('visitante_success.html', nome=nome, estado=estado, acesso=acesso)
    return render_template('visitante.html', estado=estado)

@app.route('/bolsista', methods=['GET','POST'])
def bolsista():
    if request.method == 'POST':
        nome      = request.form['nome']
        matricula = request.form['matricula']
        validado  = False
        if os.path.exists(BOLSISTAS_CSV):
            with open(BOLSISTAS_CSV,'r') as f:
                for row in csv.reader(f):
                    if row and row[0]==nome and row[1]==matricula:
                        validado = True
                        break
        if not validado:
            flash('Bolsista não cadastrado.', 'danger')
            return render_template('bolsista_fail.html')

        abrir_porta(100)
        flash('Bolsista validado. Porta e LED acionados!', 'success')
        return render_template('bolsista_success.html', nome=nome, matricula=matricula, estado=get_estado_lab())
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
        updated = False
        for i in range(len(rows)-1, 0, -1):
            r = rows[i]
            if r[0]==nome and r[1]==matricula and r[4]=='':
                ent_dt = datetime.strptime(f"{r[2]} {r[3]}", '%Y-%m-%d %H:%M:%S')
                dur_min = round((now - ent_dt).total_seconds() / 60, 2)
                r[4] = time_str
                r[5] = str(dur_min)
                flash(f'Ponto de Saída: {date_str}, {time_str} (duração {dur_min} min)', 'success')
                updated = True
                break
        if not updated:
            flash('Nenhuma entrada pendente encontrada.', 'danger')
    with open(PONTOS_CSV,'w', newline='') as f:
        csv.writer(f).writerows(rows)
    enviar_para_sheets({'id': matricula, 'nome': nome, 'acao': acao.upper(), 'data': date_str, 'hora': time_str})
    return render_template('bolsista_success.html', nome=nome, matricula=matricula, estado=get_estado_lab())

@app.route('/led/<action>')
def led_action(action):
    if action.lower() == 'on':
        control_led(True)
        flash('LED ligado no ESP32!', 'success')
    elif action.lower() == 'off':
        control_led(False)
        flash('LED desligado no ESP32.', 'info')
    else:
        flash('Ação inválida para LED.', 'danger')
    return redirect(url_for('home'))

@app.route('/admin')
@login_required
def admin():
    return render_template('admin.html')

@app.route('/cadastrar_bolsista', methods=['POST'])
@login_required
def cadastrar_bolsista():
    nome = request.form['nome']
    matricula = request.form['matricula']
    with open(BOLSISTAS_CSV,'a', newline='') as f:
        csv.writer(f).writerow([nome, matricula])
    flash('Bolsista cadastrado com sucesso!', 'success')
    return redirect(url_for('admin'))

@app.route('/remover_bolsista', methods=['POST'])
@login_required
def remover_bolsista():
    chave = request.form['chave'].strip()
    rows = []
    removido = False
    if os.path.exists(BOLSISTAS_CSV):
        with open(BOLSISTAS_CSV,'r', newline='') as f:
            for row in csv.reader(f):
                if row and (row[0]!=chave and row[1]!=chave):
                    rows.append(row)
                else:
                    removido = True
    with open(BOLSISTAS_CSV,'w', newline='') as f:
        csv.writer(f).writerows(rows)
    flash('Bolsista removido!' if removido else 'Bolsista não encontrado.', 'success' if removido else 'danger')
    return redirect(url_for('admin'))

@app.route('/atualizar_estado', methods=['POST'])
def atualizar_estado():
    novo = request.form.get('estado')
    if novo:
        set_estado_lab(novo)
        flash(f"Estado do laboratório atualizado para: {novo}", 'info')
    else:
        flash('Nenhum estado fornecido.', 'warning')
    return redirect(url_for('index'))

# ===== Executar =====
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', use_reloader=False)
