import asyncio
from bleak import BleakScanner, BleakClient, BleakError
import numpy as np
import cv2
from deepface import DeepFace

# Load face cascade classifier
FACE_CLASSIFIER = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')


# UUID del servizio e delle caratteristiche
SERVICE_UUID      = "19B10000-E8F2-537E-4F6C-D104768A1214"
CONTROL_CHAR_UUID = "19B10001-E8F2-537E-4F6C-D104768A1214"
STATUS_CHAR_UUID  = "19B10002-E8F2-537E-4F6C-D104768A1214"
IMAGE_CHAR_UUID   = "19B10003-E8F2-537E-4F6C-D104768A1214"

# Dimensioni immagine NICLA (come nello sketch)
WIDTH = int(160/2)
HEIGHT = int(120/2)
BYTES_PER_PIXEL = 1
FRAME_SIZE = WIDTH * HEIGHT * BYTES_PER_PIXEL

BLE_NOME_NICLA = "NiclaCam"

def gray_to_image(data: bytes) -> np.ndarray:
    '''
    Conversione immagine in formato array in gray scale in matrice a un canale 
    
    :param data: dati raw
    :type data: bytes
    :return: dati raw in matrice
    :rtype: ndarray[Any, Any]
    '''
    if len(data) != FRAME_SIZE:
        raise ValueError(f"Dati dimensione errata: {len(data)} byte, attesi {FRAME_SIZE}")
    
    # Converti i byte direttamente in array numpy
    gray_array = np.frombuffer(data, dtype=np.uint8)
    
    # Rimodella alle dimensioni dell'immagine
    gray_image = gray_array.reshape((HEIGHT, WIDTH))
    
    return gray_image


def rgb565_to_rgb888(data: bytes) -> np.ndarray:
    '''
    Conversione immagine in formato array da rgb565 a matrice a tre canali rgb888
    
    :param data: dati raw in formato rgb565 
    :type data: bytes
    :return: dati raw in formato rgb888
    :rtype: ndarray[Any, Any]
    '''
    pixels16 = np.frombuffer(data, dtype='>u2')  # < = little-endian, u2 = uint16
    if pixels16.size != WIDTH * HEIGHT:
        raise ValueError(f"Numero pixel errato: {pixels16.size}, atteso {WIDTH * HEIGHT}")

    r5 = (pixels16 >> 11) & 0x1F
    g6 = (pixels16 >> 5) & 0x3F
    b5 = pixels16 & 0x1F

    r8 = (r5 * 255 // 31).astype(np.uint8)
    g8 = (g6 * 255 // 63).astype(np.uint8)
    b8 = (b5 * 255 // 31).astype(np.uint8)

    rgb = np.stack([r8, g8, b8], axis=-1)      # shape (N,3)
    rgb = rgb.reshape((HEIGHT, WIDTH, 3))      # shape (120,160,3)
    return rgb


async def trova_dispositivo_BLE(nome):
    '''
    Scansione del BLE in ricerca del dispositivo "nome" 

    :param nome: Nome del dispositivo BLE da cercare
    '''
    print(f"[LOG] -- Scansione del BLE in ricerca di {BLE_NOME_NICLA}...")
    dispositivi_disponibili = await BleakScanner.discover(timeout=5.0)
    dispositivo = None
    for d in dispositivi_disponibili:
        if d.name == nome:
            dispositivo = d

    if dispositivo is not None:
        print(f"[LOG] -- Dispositivo '{nome}' trovato all'indirizzo: {dispositivo.address}")
    else:
        print(f"[ERR] -- Dispositivo '{nome}' non trovato!")

    return dispositivo

def filtro_emozioni(emozione):
    if emozione == 'happy':
        return 'felice'
    elif emozione == 'surprise':
        return 'sorpreso'
    return 'sconosciuto'

def rileva_emozioni(img_gray: np.ndarray , img_rgb: np.ndarray) :
    # Detect faces in the frame
    faccie = FACE_CLASSIFIER.detectMultiScale(img_gray, scaleFactor=1.1, minNeighbors=5, minSize=(150, 150))

    emozioni = []
    for (x, y, w, h) in faccie:
        # Estrazione della ROI (Region of Interest)
        face_roi = img_rgb[y:(y + h), x:(x + w)]

        risultato = DeepFace.analyze(face_roi, actions=['emotion'], enforce_detection=False)

        emozione = filtro_emozioni(risultato[0]['dominant_emotion'])

        cv2.rectangle(img_rgb, (x, y), (x + w, y + h), (0, 0, 255), 2)
        cv2.putText(img_rgb, f"{emozione}", (x+5, y + h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)

        print(f"[LOG] -- Emozione rilevata: {emozione}")
        emozioni.append(emozione)

    return emozioni

def conversione_raw(raw_data) -> tuple[np.ndarray, np.ndarray]:
    fattore_di_scala = 8
    img = np.frombuffer(raw_data, dtype=np.uint8).reshape(HEIGHT, WIDTH)
    img = cv2.resize(img , (WIDTH*fattore_di_scala , HEIGHT*fattore_di_scala))

    # Conversione fittizia in RGB
    img_rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    
    return img , img_rgb

def connessione_servizi(client):
    print("[LOG] -- Connesso, ricerca dei serivzi...")
    svcs = client.services
    
    if svcs is None:
        print("[ERR] -- Nessun servizio trovato! ")
        return

    print("[LOG] -- Serivizi trovati:")
    for i , s in enumerate(svcs):
        print(f"[LOG] --        {i+1}. Servizio: {s.uuid}")
        for j , ch in enumerate(s.characteristics):
            print(f"[LOG] --                {j+1}. Caratteristiche: {ch.properties}")

    service_uuids = [s.uuid.lower() for s in svcs]
    if SERVICE_UUID.lower() not in service_uuids:
        print("[ERR] -- Servizio camera non trovato sul dispositivo!")
        return

async def ricevi_dati(image_data, notification_handler, client):
    await client.start_notify(IMAGE_CHAR_UUID, notification_handler)
    await client.write_gatt_char(CONTROL_CHAR_UUID, bytearray([1]), response=True)

    timeout_s = 10.0
    waited = 0.0
    interval = 0.1

                # Attesa della ricezione dei dati
    while len(image_data) < FRAME_SIZE and waited < timeout_s:
        await asyncio.sleep(interval)
        waited += interval

    await client.stop_notify(IMAGE_CHAR_UUID)



async def main():
    dispositivo = await trova_dispositivo_BLE(BLE_NOME_NICLA)
    if dispositivo is None:
        return

    indirizzo = dispositivo.address
    image_data = bytearray()

    # Handler chiamato ad ogni notifica sull'immagine
    def notification_handler(handle , data: bytes):
        nonlocal image_data
        image_data.extend(data)

    print(f"[LOG] -- Connessiona a {indirizzo}...")
    try:
        # Connessione con il dispositivo
        async with BleakClient(indirizzo, timeout=20.0) as client:
            
            connessione_servizi(client)
            
            while(True):
                image_data.clear()
                
                await ricevi_dati(image_data, notification_handler, client)

                if len(image_data) < FRAME_SIZE:
                    print(f"[ERR] -- Timeout: ricevuti solo {len(image_data)} byte su {FRAME_SIZE} attesi.")
                    continue

                frame_bytes = bytes(image_data[:FRAME_SIZE])

                img_gray , img_rgb = conversione_raw(frame_bytes)

                emozioni = rileva_emozioni(img_gray , img_rgb)

                cv2.imshow('Camera Real Time', img_rgb)
                
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

            await client.disconnect()    

    except BleakError as e:
        print("[ERR] -- Errore BLE:", e)
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())