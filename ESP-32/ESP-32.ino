#include <WiFi.h>
#include <WebServer.h>

// ————— CONFIGURAÇÃO WIFI —————
const char* SSID     = "CNAT-MAKE-DMZ";
const char* PASSWORD = "Cnat@Maker";

// Pinos
const int RELAY_PIN = 26;  // relé para abrir a porta
const int LED_PIN   = 15;   // LED de status (interna do ESP32)

// servidor HTTP
WebServer server(80);

// Página HTML servida na raiz
const char PAGE_INDEX[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>Abrir Porta – CNATMaker</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body { font-family: Arial, sans-serif; padding:20px; background:#f4f4f4; color:#333; }
    .container { max-width:300px; margin:auto; background:#fff; padding:20px; border-radius:8px;
                 box-shadow:0 4px 12px rgba(0,0,0,0.1); text-align:center; }
    input, button { display:block; width:100%; margin-bottom:12px; }
    input { padding:8px; font-size:1rem; border:1px solid #ccc; border-radius:4px; }
    button { padding:12px; font-size:1rem; font-weight:bold; border:none; border-radius:4px;
             cursor:pointer; background:#28a745; color:#fff; transition:background .2s; }
    button:hover { background:#218838; }
    .status { margin-top:12px; font-size:.9rem; }
  </style>
</head>
<body>
  <div class="container">
    <h2>Controle CNATMaker</h2>
    <input type="text" id="esp" value="http://192.168.0.53">
    <button id="btn-open">Abrir Porta</button>
    <div class="status" id="status">Pronto.</div>
  </div>
  <script>
    const input   = document.getElementById('esp');
    const btnOpen = document.getElementById('btn-open');
    const status  = document.getElementById('status');

    function openDoor() {
      let base = input.value.trim();
      if (!base) {
        status.textContent = 'Informe o endereço do ESP32!';
        return;
      }
      base = base.replace(/\/+$/, '');
      const url = base + '/open';
      status.textContent = 'Enviando comando...';
      fetch(url)
        .then(r => {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.text();
        })
        .then(txt => status.textContent = 'Resposta: ' + txt)
        .catch(err => status.textContent = 'Erro: ' + err);
    }

    btnOpen.addEventListener('click', openDoor);
  </script>
</body>
</html>
)rawliteral";

// / – atende com a página acima
void handleRoot() {
  server.send_P(200, "text/html; charset=utf-8", PAGE_INDEX);
}

// /open – aciona relé e LED por 5 segundos
void handleOpen() {
  digitalWrite(RELAY_PIN, HIGH);
  digitalWrite(LED_PIN,   HIGH);
  delay(5000);            // pulso de 5000 ms
  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(LED_PIN,   LOW);
  server.send(200, "text/plain", "OK");
}

// 404
void handleNotFound() {
  server.send(404, "text/plain", "Not found");
}

void setup() {
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(LED_PIN,   OUTPUT);
  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(LED_PIN,   LOW);

  Serial.begin(115200);
  delay(100);

  WiFi.begin(SSID, PASSWORD);
  Serial.print("Conectando ao Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Conectado! IP: ");
  Serial.println(WiFi.localIP());

  server.on("/",      handleRoot);
  server.on("/open",  handleOpen);
  server.onNotFound(  handleNotFound);

  server.begin();
  Serial.println("HTTP server iniciado");
}

void loop() {
  server.handleClient();
}
