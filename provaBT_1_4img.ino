#include <camera.h>
#include <ArduinoBLE.h>
#include "gc2145.h"      // Sensore camera Nicla Vision

// -------------------------
// Camera (Nicla Vision, GC2145, RGB565 160x120)
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
// BLE: servizio + caratteristiche
// -------------------------
// UUID di esempio
BLEService camService("19B10000-E8F2-537E-4F6C-D104768A1214");

// Caratteristica di controllo: il centrale scrive 1 per chiedere una foto
BLEByteCharacteristic controlChar("19B10001-E8F2-537E-4F6C-D104768A1214", BLEWrite);

// Caratteristica di stato: 0 = idle, 1 = sto inviando
BLEByteCharacteristic statusChar("19B10002-E8F2-537E-4F6C-D104768A1214", BLERead | BLENotify);

// Caratteristica dati immagine (notifiche a chunk)
BLECharacteristic imageChar("19B10003-E8F2-537E-4F6C-D104768A1214", BLENotify, 20);

// -------------------------
// SETUP
// -------------------------
void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("Nicla Vision - BLE Camera");


  // LED onboard (Nicla Vision non richiede Nicla_System)
  pinMode(LEDR, OUTPUT);
  pinMode(LEDG, OUTPUT);
  pinMode(LEDB, OUTPUT);
  digitalWrite(LEDR, HIGH);
  digitalWrite(LEDG, HIGH);
  digitalWrite(LEDB, HIGH);

  // Inizializza camera 160x120 RGB565
  if (!cam.begin(CAMERA_R160x120, CAMERA_GRAYSCALE, 30)) {
    Serial.println("Camera no Start");
    while (1);
  } else {
    Serial.println("Camera Start");
  }

  // Prima immagine dummy
  cam.grabFrame(fb, 40);

  // Inizializza BLE
  if (!BLE.begin()) {
    Serial.println("BLE begin failed!");
    while (1);
  }
  BLE.setLocalName("NiclaCam");
  BLE.setDeviceName("NiclaCam");
  BLE.setAdvertisedService(camService);

  // Aggiungi caratteristiche al servizio
  camService.addCharacteristic(controlChar);
  camService.addCharacteristic(statusChar);
  camService.addCharacteristic(imageChar);

  // Aggiungi servizio allo stack BLE
  BLE.addService(camService);

  // Stato iniziale
  statusChar.writeValue((byte)0);

  // Inizia advertising
  BLE.advertise();
  Serial.println("BLE advertising started, device name: NiclaCam");
}

// -------------------------
// LOOP
// -------------------------
void loop() {
  // Aspetta un centrale che si connette
  BLEDevice central = BLE.central();

  if (central) {
    Serial.print("Connected to central: ");
    Serial.println(central.address());

    while (central.connected()) {
      // Se il centrale ha scritto sulla caratteristica di controllo
      if (controlChar.written()) {
        byte cmd = controlChar.value();
        Serial.print("Control command: ");
        Serial.println(cmd);

        if (cmd == 1) {
          // Comando "scatta e invia"
          TakePicture_Function();
          if (PictureStatus_allowsendPicture) {
            statusChar.writeValue((byte)1);  // sto mandando
            digitalWrite(LEDR, LOW);         // LED rosso ON
            sendImageOverBLE();
            digitalWrite(LEDR, HIGH);        // LED rosso OFF
            statusChar.writeValue((byte)0);  // finito
          }
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
  Serial.println("InI Snapshot");
  if (PictureStatus_allowtakePicture) {
    if (cam.grabFrame(fb, 8000) == 0) {  // timeout un po' più alto
      PictureStatus_allowsendPicture = true;
      PictureStatus_allowtakePicture = false;
      Serial.println("<<<<< Snapshot >>>>>>");
    } else {
      Serial.println("Snapshot failed or timeout");
    }
  }
}

// Invia SOLO il primo quarto (in alto a sinistra) dell'immagine
void sendImageOverBLE() {
  if (!PictureStatus_allowsendPicture) {
    Serial.println("No picture to send");
    return;
  }

  // Parametri immagine
  const int IMG_W = 160;   // larghezza completa
  const int IMG_H = 120;   // altezza completa

  // Quadrante in alto a sinistra
  const int Q_W = IMG_W / 2;  // 80
  const int Q_H = IMG_H / 2;  // 60

  // Byte totali del quadrante
  const size_t quarterSize = Q_W * Q_H;  // 80 * 60 = 4800

  // Buffer per il quadrante (static per non usare troppo stack)
  static uint8_t quarterBuf[Q_W * Q_H];

  // Puntatore all'immagine completa
  uint8_t* src = (uint8_t*)fb.getBuffer();

  // Copia riga per riga: dalle prime 60 righe, solo i primi 80 pixel
  for (int y = 0; y < Q_H; y++) {
    // offset riga intera nell'immagine sorgente
    int srcRowOffset = y * IMG_W;
    // offset riga nel buffer quadrante
    int dstRowOffset = y * Q_W;

    // copia i primi 80 byte di questa riga
    memcpy(&quarterBuf[dstRowOffset], &src[srcRowOffset], Q_W);
  }

  Serial.print("Sending TOP-LEFT quarter, size = ");
  Serial.println(quarterSize);

  const size_t chunkSize = 20;  // tipico MTU BLE con ArduinoBLE

  size_t offset = 0;
  while (offset < quarterSize) {
    size_t len = quarterSize - offset;
    if (len > chunkSize) len = chunkSize;

    // manda un chunk come notifica
    imageChar.writeValue(quarterBuf + offset, len);

    offset += len;

    // Piccola pausa per non saturare lo stack BLE
    //delay(0);  // puoi provare a mettere 0 o 1 per più velocità
  }

  Serial.println("Image quarter send complete");

  // Resetta flag per prossimo scatto
  PictureStatus_allowsendPicture = false;
  PictureStatus_allowtakePicture = true;
}