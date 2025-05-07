import csv
import os
import sys
from urllib.parse   import urlencode
from urllib.request import urlopen
from flask import Flask, render_template, request, redirect, url_for, flash, session
from threading import Timer
from datetime import datetime
from functools import wraps

# ===== Configurações Básicas =====
app = Flask(__name__)
app.secret_key = 'super_secret_key'
@app.context_processor
def inject_is_admin():
    return { 'is_admin': session.get('is_admin', False) }


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
            print("[GPIO SIMULADO] pino {} -> {}".format(pin, value))
else:
    import RPi.GPIO as GPIO

DOOR_PIN = 17
GPIO.setmode(GPIO.BCM)
GPIO.setup(DOOR_PIN, GPIO.OUT)
GPIO.output(DOOR_PIN, GPIO.LOW)

# ===== Arquivos de dados =====
BOLSISTAS_CSV     = 'bolsistas.csv'
VISITAS_CSV       = 'visitas.csv'
PONTOS_CSV        = 'pontos.csv'
ESTADO_LAB_TXT    = 'estado_lab.txt'

# ===== Google Sheets Web App URL =====
SHEETS_WEBAPP_URL = 'https://script.google.com/macros/s/AKfycbwXd3B25eg-DXrem3KZ0Yel3HavuHlS8X5gXAgtCdl6DklQiu2fS-R6W2YQaeF2Jjix/exec'

# ===== Senha de acesso ao Admin =====
ADMIN_PASSWORD = 'maker22'  # <— defina aqui sua senha de administrador
# ===== Inicialização de arquivos =====
if not os.path.exists(ESTADO_LAB_TXT):
    with open(ESTADO_LAB_TXT, 'w') as f:
        f.write('FECHADO')

if not os.path.exists(PONTOS_CSV):
    with open(PONTOS_CSV, 'w', newline='') as f:
        csv.writer(f).writerow(['Nome','ID','Data','Entrada','Saída','Duração(min)'])

# ===== Helper: simular/acionar porta =====
def abrir_porta():
    GPIO.output(DOOR_PIN, GPIO.HIGH)
    Timer(5, lambda: GPIO.output(DOOR_PIN, GPIO.LOW)).start()

# ===== Helper: estado do laboratório =====
def get_estado_lab():
    return open(ESTADO_LAB_TXT).read().strip().upper()

def set_estado_lab(novo):
    with open(ESTADO_LAB_TXT, 'w') as f:
        f.write(novo.strip().upper())

# ===== Helper: enviar dados ao Google Sheets =====
def enviar_para_sheets(params):
    qs = urlencode(params)
    url = "{}?{}".format(SHEETS_WEBAPP_URL, qs)
    try:
        with urlopen(url, timeout=5) as resp:
            text = resp.read().decode()
            app.logger.info("Sheets respondeu: {}".format(text))
    except Exception as e:
        app.logger.error("Erro enviando ao Sheets: {}".format(e))

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
        else:
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
    return render_template('index.html',
                           estado=get_estado_lab(),
                           is_admin=session.get('is_admin', False))

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
        if estado != "ABERTO":
            flash("Laboratório não está aberto para entrada.", "danger")
            return render_template('visitante.html', estado=estado)

        nome      = request.form['nome']
        matricula = request.form['matricula']
        motivo    = request.form['motivo']
        ts        = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with open(VISITAS_CSV,'a',newline='') as f:
            csv.writer(f).writerow([nome, matricula, motivo, ts])

        # Agora enviamos 'id', não 'matricula'
        enviar_para_sheets({
            'nome':     nome,
            'id':       matricula,
            'motivo':   motivo,
            'acao':     'VISITA',
            'datahora': ts
        })

        acesso = os.path.exists(BOLSISTAS_CSV) and os.path.getsize(BOLSISTAS_CSV)>0
        if acesso:
            abrir_porta()
            flash("Registro de visitante realizado e porta aberta!", "success")
        else:
            flash("Registro de visitante realizado, mas porta não aberta.", "info")

        return render_template('visitante_success.html',
                               nome=nome, estado=estado, acesso=acesso)
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
            flash("Bolsista não cadastrado.", "danger")
            return render_template('bolsista_fail.html')
        abrir_porta()
        flash("Bolsista validado. Porta aberta!", "success")
        return render_template('bolsista_success.html',
                               nome=nome,
                               matricula=matricula,
                               estado=get_estado_lab())
    return render_template('bolsista.html')

@app.route('/marcar_ponto', methods=['POST'])
def marcar_ponto():
    nome      = request.form['nome']
    matricula = request.form['matricula']
    acao      = request.form['acao']   # 'entrada' ou 'saida'
    now       = datetime.now()
    date_str  = now.strftime('%Y-%m-%d')
    time_str  = now.strftime('%H:%M:%S')

    rows = list(csv.reader(open(PONTOS_CSV,'r',newline='')))
    if acao == 'entrada':
        rows.append([nome, matricula, date_str, time_str, '', ''])
        flash("Ponto de Entrada: {}, {}".format(date_str, time_str), "success")
    else:
        updated = False
        for i in range(len(rows)-1, 0, -1):
            r = rows[i]
            if r[0]==nome and r[1]==matricula and r[4]=='':
                ent_dt = datetime.strptime(
                    "{} {}".format(r[2], r[3]),
                    '%Y-%m-%d %H:%M:%S'
                )
                dur_min = round((now - ent_dt).total_seconds() / 60, 2)
                r[4] = time_str
                r[5] = str(dur_min)
                flash("Ponto de Saída: {}, {} (duração {} min)".format(date_str, time_str, dur_min),
                      "success")
                updated = True
                break
        if not updated:
            flash("Nenhuma entrada pendente encontrada.", "danger")

    with open(PONTOS_CSV,'w',newline='') as f:
        csv.writer(f).writerows(rows)

    enviar_para_sheets({
        'id':   matricula,
        'nome': nome,
        'acao': acao.upper(),
        'data': date_str,
        'hora': time_str
    })

    return render_template('bolsista_success.html',
                           nome=nome,
                           matricula=matricula,
                           estado=get_estado_lab())

# ===== Rotas de Administração =====
@app.route('/admin')
@login_required
def admin():
    return render_template('admin.html')

@app.route('/cadastrar_bolsista', methods=['POST'])
@login_required
def cadastrar_bolsista():
    nome      = request.form['nome']
    matricula = request.form['matricula']
    with open(BOLSISTAS_CSV,'a',newline='') as f:
        csv.writer(f).writerow([nome, matricula])
    flash("Bolsista cadastrado com sucesso!", "success")
    return redirect(url_for('admin'))

@app.route('/remover_bolsista', methods=['POST'])
@login_required
def remover_bolsista():
    chave = request.form['chave'].strip()
    rows = []
    removido = False
    if os.path.exists(BOLSISTAS_CSV):
        with open(BOLSISTAS_CSV,'r',newline='') as f:
            for row in csv.reader(f):
                if row and (row[0]!=chave and row[1]!=chave):
                    rows.append(row)
                else:
                    removido = True
    with open(BOLSISTAS_CSV,'w',newline='') as f:
        csv.writer(f).writerows(rows)
    flash(
        'Bolsista removido com sucesso!' if removido else 'Bolsista não encontrado.',
        'success' if removido else 'danger'
    )
    return redirect(url_for('admin'))

@app.route('/atualizar_estado', methods=['POST'])
def atualizar_estado():
    novo = request.form.get('estado')
    if novo:
        set_estado_lab(novo)
        flash("Estado do laboratório atualizado para: {}".format(novo), "info")
    else:
        flash("Nenhum estado fornecido.", "warning")
    return redirect(url_for('index'))

# ===== Executar =====
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
