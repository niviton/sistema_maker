import serial

try:
    ser = serial.Serial('COM4', 115200, timeout=1)
    print("Aberto com sucesso em COM4!")
    ser.close()
except Exception as e:
    print("Erro ao abrir serial:", e)
