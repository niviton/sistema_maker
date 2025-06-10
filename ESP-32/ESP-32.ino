// ===== Sketch Arduino =====

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);    // usa o LED interno
  Serial.begin(115200);            // agora bate com o worker_serial.py
  delay(2000);                     // espera a conexão estabilizar
  Serial.println("Arduino pronto em 115200 baud");
}

void loop() {
  if (Serial.available()) {
    char comando = Serial.read();
    Serial.print("Recebido: ");
    Serial.println(comando);

    if (comando == '1') {
      digitalWrite(LED_BUILTIN, HIGH);
    }
    else if (comando == '0') {
      digitalWrite(LED_BUILTIN, LOW);
    }
  }
}
