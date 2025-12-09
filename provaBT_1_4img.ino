#include <camera.h>
#include <ArduinoBLE.h>
#include "gc2145.h"

// -------------------------
// Camera 
// -------------------------
GC2145 galaxyCore;
Camera cam(galaxyCore);
FrameBuffer fb;

// -------------------------
// Stato foto
// -------------------------
bool PictureStatus_allowtakePicture  = true;   // posso scattare una nuova foto
bool PictureStatus_allowsendPicture  = false;  // ho una foto pronta da inviare

// -------------------------
// BLE
// -------------------------
BLEService camService("19B10000-E8F2-537E-4F6C-D104768A1214");
BLEByteCharacteristic controlChar("19B10001-E8F2-537E-4F6C-D104768A1214", BLEWrite);
BLEByteCharacteristic statusChar("19B10002-E8F2-537E-4F6C-D104768A1214", BLERead | BLENotify);
BLECharacteristic imageChar("19B10003-E8F2-537E-4F6C-D104768A1214", BLENotify, 20);

// -------------------------
// LED + EMOZIONI
// -------------------------

// valori per identificare le emozioni
const byte EMO_HAPPY      = 10;  
const byte EMO_SURPRISED  = 11;  
const byte EMO_UNKNOWN    = 12;  


void ledOff() {
  digitalWrite(LEDR, HIGH);
  digitalWrite(LEDG, HIGH);
  digitalWrite(LEDB, HIGH);
}

// accende/spegne i singoli colori con booleani
void ledColor(bool rOn, bool gOn, bool bOn) {
  digitalWrite(LEDR, rOn ? LOW : HIGH);
  digitalWrite(LEDG, gOn ? LOW : HIGH);
  digitalWrite(LEDB, bOn ? LOW : HIGH);
}

// LED lampeggia  con un colore diverso in base all'emozione 
void blinkEmotionLed(byte emoCode, int times = 5, int delayMs = 200) {
  Serial.print("LED: emozione codice ");
  Serial.println(emoCode);

  for (int i = 0; i < times; i++) {
    // felice      -> giallo 
    // sorpreso    -> ciano  
    // sconosciuto -> fucsia
    if (emoCode == EMO_HAPPY) {
      ledColor(true, true, false);   // giallo
      Serial.println("LED: FELICE (giallo)");
    } else if (emoCode == EMO_SURPRISED) {
      ledColor(false, true, true);   // ciano
      Serial.println("LED: SORPRESO (ciano)");
    } else {
      ledColor(true, false, true);   // fucsia
      Serial.println("LED: SCONOSCIUTO (fucsia)");
    }

    delay(delayMs);

    // spegne tutto
    ledOff();
    delay(delayMs);
  }

  Serial.println("LED: lampeggio completato");
}

// -------------------------
// SETUP
// -------------------------
void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("Nicla Vision - BLE Camera");

  pinMode(LEDR, OUTPUT);
  pinMode(LEDG, OUTPUT);
  pinMode(LEDB, OUTPUT);
  ledOff();

  // risoluzione camera 160x120 e in  grayscale->img più leggera da inviare
  if (!cam.begin(CAMERA_R160x120, CAMERA_GRAYSCALE, 30)) {
    Serial.println("Camera no Start");
    while (1);
  } else {
    Serial.println("Camera Start");
  }

  // invio prima immagine di test
  cam.grabFrame(fb, 40);

  // inizializzazione BLE
  if (!BLE.begin()) {
    Serial.println("BLE begin failed!");
    while (1);
  }
  BLE.setLocalName("NiclaCam");
  BLE.setDeviceName("NiclaCam");
  BLE.setAdvertisedService(camService);

  camService.addCharacteristic(controlChar);
  camService.addCharacteristic(statusChar);
  camService.addCharacteristic(imageChar);
  BLE.addService(camService);

  // stato iniziale: non sto inviando->0
  statusChar.writeValue((byte)0);

  // dispositivo connesso
  BLE.advertise();
  Serial.println("BLE advertising started, device name: NiclaCam");
}

// -------------------------
// LOOP
// -------------------------
void loop() {
  // aspetto che un dispositivo si connetta
  BLEDevice central = BLE.central();

  if (central) {
    Serial.print("Connected to: ");
    Serial.println(central.address());

    while (central.connected()) {
      // controllo se è stato scritto qualcosa
      if (controlChar.written()) {
        byte cmd = controlChar.value();
        Serial.print("Control command: ");
        Serial.println(cmd);

        if (cmd == 1) {
          // 1 = "scatta e invia"
          TakePicture_Function();
          if (PictureStatus_allowsendPicture) {
            statusChar.writeValue((byte)1);  // sta mandando

            // LED rosso fisso mentre invio l'immagine->sto trasmettendo
            digitalWrite(LEDR, LOW);

            sendImageOverBLE();

            statusChar.writeValue((byte)0);  // ho finito l'invio 
            digitalWrite(LEDR, HIGH);
          } else {
            Serial.println("Snapshot failed or timeout");
          }
        }
        // 10 / 11 / 12 arrivano da Python e indicano l'emozione->check valore
        else if (cmd == EMO_HAPPY || cmd == EMO_SURPRISED || cmd == EMO_UNKNOWN) {
          blinkEmotionLed(cmd);
        }
        else {
          Serial.print("Comando sconosciuto: ");
          Serial.println(cmd);
        }
      }
    }

    Serial.println("Central disconnected");
  }
}

// -------------------------
// FUNZIONI DI SUPPORTO
// -------------------------

// Scatta una foto
void TakePicture_Function() {
  Serial.println("Inizio Snapshot");
  if (PictureStatus_allowtakePicture) {
    if (cam.grabFrame(fb, 8000) == 0) {
      PictureStatus_allowsendPicture = true;
      PictureStatus_allowtakePicture = false;
      Serial.println("<<<<< Snapshot ok >>>>>>");
    } else {
      Serial.println("Snapshot failed or timeout");
    }
  }
}

// Invio solo il primo quarto (in alto a sx) dell'immagine-> quello che ci interessa
void sendImageOverBLE() {
  if (!PictureStatus_allowsendPicture) {
    Serial.println("No picture to send");
    return;
  }

  // Parametri immagine
  const int IMG_W = 160;   // larghezza tot
  const int IMG_H = 120;   // altezza tot

  // Quadrante in alto a sinistra
  const int Q_W = IMG_W / 2;  // 80->metà larghezza
  const int Q_H = IMG_H / 2;  // 60->metà lunghezza 

  // calcolo byte totali del quadrante + buffer + puntatore img
  const size_t quarterSize = Q_W * Q_H;  // 80 * 60 = 4800
  static uint8_t quarterBuf[Q_W * Q_H];
  uint8_t* src = (uint8_t*)fb.getBuffer();

  // copio riga per riga: prime 60 righe, primi 80 pixel
  for (int y = 0; y < Q_H; y++) {
    int srcRowOffset = y * IMG_W;
    int dstRowOffset = y * Q_W;
    memcpy(&quarterBuf[dstRowOffset], &src[srcRowOffset], Q_W);
  }

  Serial.print("Sending TOP-LEFT quarter, size = ");
  Serial.println(quarterSize);

  const size_t chunkSize = 20;

  size_t offset = 0;
  while (offset < quarterSize) {
    size_t len = quarterSize - offset;
    if (len > chunkSize) len = chunkSize;

    // mando un chunk come notifica
    imageChar.writeValue(quarterBuf + offset, len);

    offset += len;
  }

  Serial.println("Image quarter send complete");

  // flag resettato per prossimo scatto
  PictureStatus_allowsendPicture = false;
  PictureStatus_allowtakePicture = true;
}