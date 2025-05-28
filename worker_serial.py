import serial
import time
import os
from serial.tools import list_ports

COMANDO_FILE = 'comando.txt'
BAUD_RATE    = 115200

def auto_detect_serial():
    for p in list_ports.comports():
        desc = p.description.lower()
        if 'usb' in desc or 'cp210' in desc or 'ftdi' in desc:
            return p.device
    return None

def conectar_arduino():
    port = auto_detect_serial() or ('COM3' if os.name=='nt' else '/dev/ttyUSB0')
    try:
        arduino = serial.Serial(port, BAUD_RATE, timeout=1)
        time.sleep(2)
        print(f"[Serial] Conectado em {port}")
        return arduino
    except Exception as e:
        print(f"[Serial] Erro ao conectar: {e}")
        return None

def ler_comando():
    if os.path.exists(COMANDO_FILE):
        with open(COMANDO_FILE,'r') as f:
            cmd = f.read().strip()
        return cmd
    return None

def limpar_comando():
    with open(COMANDO_FILE,'w') as f:
        f.write('')

def main():
    arduino = conectar_arduino()
    if not arduino:
        print("Saindo: sem conexão serial.")
        return
    while True:
        cmd = ler_comando()
        if cmd in ['1','0']:
            print(f"[Serial] Enviando comando: {cmd}")
            arduino.write(cmd.encode())
            limpar_comando()
        time.sleep(0.5)

if __name__ == "__main__":
    main()
