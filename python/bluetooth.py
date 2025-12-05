import asyncio
from bleak import BleakScanner, BleakClient, BleakError
import numpy as np
import cv2

from deepface import DeepFace
# Load face cascade classifier
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')


# UUID del servizio e delle caratteristiche (devono combaciare con lo sketch Arduino)
SERVICE_UUID      = "19B10000-E8F2-537E-4F6C-D104768A1214"
CONTROL_CHAR_UUID = "19B10001-E8F2-537E-4F6C-D104768A1214"
STATUS_CHAR_UUID  = "19B10002-E8F2-537E-4F6C-D104768A1214"
IMAGE_CHAR_UUID   = "19B10003-E8F2-537E-4F6C-D104768A1214"

# Dimensioni immagine NICLA (come nello sketch)
WIDTH = int(160/2)
HEIGHT = int(120/2)
BYTES_PER_PIXEL = 1
FRAME_SIZE = WIDTH * HEIGHT * BYTES_PER_PIXEL  # 160 * 120 * 2 = 38400


def gray_to_image(data: bytes) -> np.ndarray:
    """
    Converte un buffer gray scale (160x120) in un array numpy (uint8).
    `data` deve avere lunghezza FRAME_SIZE.
    """
    if len(data) != FRAME_SIZE:
        raise ValueError(f"Dati dimensione errata: {len(data)} byte, attesi {FRAME_SIZE}")
    
    # Converti i byte direttamente in array numpy
    gray_array = np.frombuffer(data, dtype=np.uint8)
    
    # Rimodella alle dimensioni dell'immagine
    gray_image = gray_array.reshape((HEIGHT, WIDTH))
    
    return gray_image


def rgb565_to_rgb888(data: bytes) -> np.ndarray:
    """
    Converte un buffer RGB565 (160x120) in un array numpy RGB888 (uint8).
    `data` deve avere lunghezza FRAME_SIZE.
    """
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


async def find_nicla_cam():
    print("Scanning for BLE devices (looking for 'NiclaCam')...")
    devices = await BleakScanner.discover(timeout=5.0)
    nicla_device = None
    for d in devices:
        print(f"Found: name={d.name}, addr={d.address}")
        if d.name == "NiclaCam":
            nicla_device = d
    if nicla_device:
        print(f"-> Using NiclaCam at {nicla_device.address}")
    return nicla_device

def filtro_emozioni(emozione):
    if emozione == 'happy':
        return 'felice'
    elif emozione == 'surprise':
        return 'sorpreso'
    return 'sconosciuto'


async def main():
    device = await find_nicla_cam()
    if device is None:
        print("NiclaCam non trovata. Assicurati che sia accesa e in advertising.")
        return

    address = device.address
    print(f"Connecting to {address} ...")

    image_data = bytearray()

    # Handler chiamato ad ogni notifica sull'immagine
    def notification_handler(handle, data: bytes):
        nonlocal image_data
        image_data.extend(data)
        # print(f"Received chunk: {len(data)} bytes (total: {len(image_data)}/{FRAME_SIZE})")

    try:
        async with BleakClient(address, timeout=20.0) as client:
            print("Connected, reading services...")
            svcs = client.services

            print("Reading services...")
            svcs = client.services
            
            if svcs is None:
                print("Nessun servizio trovato (services è None). Probabile disconnessione.")
                return

            print("Services discovered:")
            for s in svcs:
                print(f"  Service: {s.uuid}")
                for ch in s.characteristics:
                    print(f"    Char: {ch.uuid}, props={ch.properties}")

            service_uuids = [s.uuid.lower() for s in svcs]
            if SERVICE_UUID.lower() not in service_uuids:
                print("Servizio camera non trovato sul dispositivo.")
                return
            while(True):
                image_data = bytearray()

                print("Starting notifications on IMAGE_CHAR...")
                await client.start_notify(IMAGE_CHAR_UUID, notification_handler)

                print("Sending capture command (1) to CONTROL_CHAR...")
                await client.write_gatt_char(CONTROL_CHAR_UUID, bytearray([1]), response=True)

                # Aspetta che i dati arrivino (o timeout)
                timeout_s = 15.0
                waited = 0.0
                interval = 0.01

                while len(image_data) < FRAME_SIZE and waited < timeout_s:
                    await asyncio.sleep(interval)
                    waited += interval

                await client.stop_notify(IMAGE_CHAR_UUID)

                if len(image_data) < FRAME_SIZE:
                    print(f"Timeout: ricevuti solo {len(image_data)} byte su {FRAME_SIZE} attesi.")
                    return

                frame_bytes = bytes(image_data[:FRAME_SIZE])
                print("Frame completo ricevuto, convertendo in immagine...")


                FATTORE = 8
                img = np.frombuffer(frame_bytes, dtype=np.uint8).reshape(HEIGHT, WIDTH)
                img = cv2.resize(img , (WIDTH*FATTORE , HEIGHT*FATTORE))
                rgb_img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)

                # cv2.imshow("fotina" , img)
                # cv2.waitKey(0)
                # Detect faces in the frame
                faces = face_cascade.detectMultiScale(img, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

                for (x, y, w, h) in faces:
                    # Extract the face ROI (Region of Interest)
                    face_roi = rgb_img[y:y + h, x:x + w]

                    # Perform emotion analysis on the face ROI
                    result = DeepFace.analyze(face_roi, actions=['emotion'], enforce_detection=False)

                    # Determine the dominant emotion
                    emotion = result[0]['dominant_emotion']
                    # age = result[0]['age']

                    emotion = filtro_emozioni(emotion)

                    # Draw rectangle around face and label with predicted emotion
                    cv2.rectangle(rgb_img, (x, y), (x + w, y + h), (0, 0, 255), 2)
                    cv2.putText(rgb_img, f"{emotion}", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
                    print(emotion)

                # # Display the resulting img
                cv2.imshow('Real-time Emotion Detection', rgb_img)
                # Press 'q' to exit
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break


            # gray_img = gray_to_image(frame_bytes)
            # # rgb_img = rgb565_to_rgb888(frame_bytes)
            # img = Image.fromarray(gray_img, mode='L')
            # img.save("nicla_ble_frame.png")
            # print("Immagine salvata come nicla_ble_frame.png")
            # img.show()

    except BleakError as e:
        print("Errore BLE:", e)

if __name__ == "__main__":
    asyncio.run(main())