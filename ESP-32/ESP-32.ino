// serial_relay.ino

const int RELAY_PIN = 26;   // seu pino de relé
const int LED_PIN   = 15;    // GPIO2, LED embutido em muitos módulos DevKit

void setup() {
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  Serial.begin(115200);
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd.equalsIgnoreCase("OPEN")) {
      // Pulso no relé
      digitalWrite(RELAY_PIN, HIGH);
      delay(2000);
      digitalWrite(RELAY_PIN, LOW);
      Serial.println("RELAY_OPENED");

    } else if (cmd.equalsIgnoreCase("LED_ON")) {
      digitalWrite(LED_PIN, HIGH);
      Serial.println("LED_ON_OK");

    } else if (cmd.equalsIgnoreCase("LED_OFF")) {
      digitalWrite(LED_PIN, LOW);
      Serial.println("LED_OFF_OK");
    }
  }
}
