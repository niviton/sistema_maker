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

# ===== Configurações Básicas =====
app = Flask(__name__)
app.secret_key = 'super_secret_key'

@app.context_processor
def inject_is_admin():
    return {'is_admin': session.get('is_admin', False)}

# ===== Parâmetros de Serial =====
ENV_PORT = os.getenv('USB_SERIAL_PORT')
FALLBACK_PORT = 'COM4' if sys.platform.startswith("win") else '/dev/ttyUSB0'
BAUD_RATE = 115200

ser = None
_ser_lock = threading.Lock()

def auto_detect_serial():
    for p in list_ports.comports():
        d = p.description.lower()
        if 'usb' in d or 'cp210' in d or 'ftdi' in d:
            return p.device
    return None

def serial_monitor():
    global ser
    first_success = False
    while True:
        if ser is None or not getattr(ser, 'is_open', False):
            port = ENV_PORT or auto_detect_serial() or FALLBACK_PORT
            try:
                s = serial.Serial(port, BAUD_RATE, timeout=1)
                time.sleep(2)  # aguarda boot do ESP
                with _ser_lock:
                    ser = s
                if not first_success:
                    app.logger.info(f"[SERIAL] Conectado a {port}")
                    first_success = True
            except Exception:
                # falha silenciosa; continua tentando
                pass
        time.sleep(5)

# dispara thread de monitoramento em background
threading.Thread(target=serial_monitor, daemon=True).start()

# ===== GPIO simulado ou real =====
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
SHEETS_WEBAPP_URL = 'https://script.google.com/macros/s/AKfycbwXd3B25eg-DXrem3KZ0Yel3HavuHlS8X5gXAgtCdl6DklQiu2fS-R6W2YQaeF2Jjix/exec'
ADMIN_PASSWORD = 'maker22'

# inicializa arquivos
for path, header in [
    (ESTADO_LAB_TXT, None),
    (VISITAS_CSV,    None),
    (BOLSISTAS_CSV,  None),
    (PONTOS_CSV,     ['Nome','ID','Data','Entrada','Saída','Duração(min)']),
]:
    if not os.path.exists(path):
        if header is None:
            open(path, 'w').close()
        else:
            with open(path, 'w', newline='') as f:
                csv.writer(f).writerow(header)

# ===== Controle de LED e porta =====
def control_led(turn_on: bool):
    with _ser_lock:
        s = ser
    if s and s.is_open:
        cmd = b'LED_ON\n' if turn_on else b'LED_OFF\n'
        try:
            s.write(cmd)
        except:
            pass

def abrir_porta(pulse_ms: int = 100):
    with _ser_lock:
        s = ser
    if s and s.is_open:
        try:
            s.write(b'OPEN\n')
        except:
            pass
    else:
        def _pulse_gpio():
            GPIO.output(DOOR_PIN, GPIO.HIGH)
            time.sleep(pulse_ms/1000)
            GPIO.output(DOOR_PIN, GPIO.LOW)
        threading.Thread(target=_pulse_gpio, daemon=True).start()
    # pisca LED
    control_led(True)
    threading.Timer(pulse_ms/1000, lambda: control_led(False)).start()

# ===== Estado do laboratório =====
def get_estado_lab():
    return open(ESTADO_LAB_TXT).read().strip().upper()
def set_estado_lab(novo):
    with open(ESTADO_LAB_TXT,'w') as f:
        f.write(novo.strip().upper())

# ===== Envio ao Sheets =====
def _send_to_sheets(params):
    url = f"{SHEETS_WEBAPP_URL}?{urlencode(params)}"
    try:
        with urlopen(url, timeout=5) as resp:
            app.logger.info("[SHEETS] " + resp.read().decode())
    except:
        pass

def enviar_para_sheets(params):
    threading.Thread(target=_send_to_sheets,args=(params,),daemon=True).start()

# ===== Autenticação =====
def login_required(f):
    @wraps(f)
    def dec(*a,**k):
        if not session.get('is_admin'):
            return redirect(url_for('login'))
        return f(*a,**k)
    return dec

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        if request.form.get('senha','')==ADMIN_PASSWORD:
            session['is_admin']=True
            flash('Login bem-sucedido!','success')
            return redirect(url_for('admin'))
        flash('Senha incorreta.','danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('is_admin',None)
    flash('Logout efetuado.','info')
    return redirect(url_for('home'))

# ===== Rotas públicas =====
@app.route('/')
def index(): return redirect(url_for('home'))
@app.route('/home')
def home():
    return render_template('home.html',
        estado=get_estado_lab(),
        is_admin=session.get('is_admin',False)
    )
@app.route('/iniciar', methods=['POST'])
def iniciar(): return redirect(url_for('home'))

@app.route('/visitante', methods=['GET','POST'])
def visitante():
    estado = get_estado_lab()
    if request.method=='POST':
        if estado!='ABERTO':
            flash('Lab fechado.','danger')
            return render_template('visitante.html',estado=estado)
        nome,mat,mot = request.form['nome'],request.form['matricula'],request.form['motivo']
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(VISITAS_CSV,'a',newline='') as f:
            csv.writer(f).writerow([nome,mat,mot,ts])
        acesso = os.path.getsize(BOLSISTAS_CSV)>0
        if acesso:
            abrir_porta(100); flash('Visitante OK!','success')
        else:
            flash('Visitante registrado.','info')
        params = {'nome':nome,'id':mat,'motivo':mot,'acao':'VISITA','datahora':ts}
        enviar_para_sheets(params)
        return render_template('visitante_success.html',nome=nome,estado=estado,acesso=acesso)
    return render_template('visitante.html',estado=estado)

@app.route('/bolsista', methods=['GET','POST'])
def bolsista():
    if request.method=='POST':
        nome,mat = request.form['nome'],request.form['matricula']
        ok=False
        with open(BOLSISTAS_CSV) as f:
            for r in csv.reader(f):
                if r and r[0]==nome and r[1]==mat: ok=True; break
        if not ok:
            flash('Não cadastrado.','danger')
            return render_template('bolsista_fail.html')
        abrir_porta(100)
        flash('Bolsista OK!','success')
        return render_template('bolsista_success.html',nome=nome,matricula=mat,estado=get_estado_lab())
    return render_template('bolsista.html')

@app.route('/marcar_ponto', methods=['POST'])
def marcar_ponto():
    nome,mat,acao = request.form['nome'],request.form['matricula'],request.form['acao']
    now = datetime.now()
    ds,ts = now.strftime('%Y-%m-%d'),now.strftime('%H:%M:%S')
    rows=list(csv.reader(open(PONTOS_CSV,'r',newline='')))
    if acao=='entrada':
        rows.append([nome,mat,ds,ts,'','']); flash(f'Entrou {ds} {ts}','success')
    else:
        upd=False
        for i in range(len(rows)-1,0,-1):
            r=rows[i]
            if r[0]==nome and r[1]==mat and r[4]=='':
                ent=datetime.strptime(f"{r[2]} {r[3]}","%Y-%m-%d %H:%M:%S")
                dur=round((now-ent).total_seconds()/60,2)
                r[4]=ts; r[5]=str(dur)
                flash(f'Saiu {ds} {ts} ({dur}min)','success'); upd=True; break
        if not upd: flash('Nenhuma entrada.','danger')
    with open(PONTOS_CSV,'w',newline='') as f:
        csv.writer(f).writerows(rows)
    enviar_para_sheets({'id':mat,'nome':nome,'acao':acao.upper(),'data':ds,'hora':ts})
    return render_template('bolsista_success.html',nome=nome,matricula=mat,estado=get_estado_lab())

@app.route('/admin')
@login_required
def admin():
    return render_template('admin.html')
@app.route('/cadastrar_bolsista',methods=['POST'])
@login_required
def cadastrar_bolsista():
    n,m=request.form['nome'],request.form['matricula']
    with open(BOLSISTAS_CSV,'a',newline='')as f: csv.writer(f).writerow([n,m])
    flash('Bolsista adicionado.','success'); return redirect(url_for('admin'))
@app.route('/remover_bolsista',methods=['POST'])
@login_required
def remover_bolsista():
    chave=request.form['chave'].strip(); rows=[]; rem=False
    with open(BOLSISTAS_CSV)as f:
        for r in csv.reader(f):
            if r and (r[0]!=chave and r[1]!=chave): rows.append(r)
            else: rem=True
    with open(BOLSISTAS_CSV,'w',newline='')as f: csv.writer(f).writerows(rows)
    flash('Removido.' if rem else 'Não encontrado.','success' if rem else 'danger')
    return redirect(url_for('admin'))

@app.route('/atualizar_estado',methods=['POST'])
def atualizar_estado():
    novo=request.form.get('estado')
    if novo: set_estado_lab(novo); flash(f'Estado: {novo}','info')
    else: flash('Nenhum estado.','warning')
    return redirect(url_for('home'))

if __name__=='__main__':
    app.run(debug=True,host='0.0.0.0',use_reloader=False)
