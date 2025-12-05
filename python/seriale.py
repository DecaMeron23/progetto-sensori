import serial
import numpy as np
import cv2
from deepface import DeepFace


def main():
    PORTA = "/dev/ttyACM0"
    BAUDRATE = 115200
    NUMERO_BYTE_PER_PIXEL = 2
    
    # Load face cascade classifier
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')


    # Creo il seriale
    ser = creazione_seriale(PORTA, BAUDRATE)

    # ser.reset_input_buffer()
    while True:
        
        # Attesa della sincronizzazione
        attesa_sincronizzazione(ser)

        width, height , size = estrazione_informazioni_immagine(ser)

        # Lettura da seriale: immagine
        img_data = leggi_byte(ser, size)

        img = np.frombuffer(img_data, dtype=np.uint8).reshape((height, width , NUMERO_BYTE_PER_PIXEL))

        # Inversione dei byte (OPENCV li vuole inversi... almeno 1 ora per capirlo, p.s. grazie Chatty)
        img = img[:, :, ::-1]  
        img = cv2.cvtColor(img, cv2.COLOR_BGR5652BGR)
        
        # Convert frame to grayscale
        gray_frame = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Convert grayscale frame to RGB format 
        rgb_frame = cv2.cvtColor(gray_frame, cv2.COLOR_GRAY2RGB)

        # Detect faces in the frame
        faces = face_cascade.detectMultiScale(gray_frame, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

        for (x, y, w, h) in faces:
            # Extract the face ROI (Region of Interest)
            face_roi = rgb_frame[y:y + h, x:x + w]

            # Perform emotion analysis on the face ROI
            result = DeepFace.analyze(face_roi, actions=['emotion'], enforce_detection=False)

            # Determine the dominant emotion
            emotion = result[0]['dominant_emotion']
            # age = result[0]['age']
            confidence = result[0]['face_confidence']

            emotion = filtro_emozioni(emotion)

            if confidence >= .85:
                # Draw rectangle around face and label with predicted emotion
                cv2.rectangle(img, (x, y), (x + w, y + h), (0, 0, 255), 2)
                cv2.putText(img, f"{emotion}", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
                print(emotion)

        # Display the resulting frame
        cv2.imshow('Real-time Emotion Detection', img)

        # Press 'q' to exit
        if cv2.waitKey(1) & 0xFF == ord('q'):
            ser.close()
            break


def filtro_emozioni(emozione):
    if emozione == 'happy':
        return 'felice'
    elif emozione == 'surprise':
        return 'sorpreso'
    return 'sconosciuto'


def estrazione_informazioni_immagine(ser):
    # Lettura da seriale: dimensioni dell'immagine WxH
    wh = leggi_byte(ser, 4)
    width  = int.from_bytes(wh[:2], 'little')
    height = int.from_bytes(wh[2:], 'little')

    # Lettura da seriale: numero di byte totali
    size_bytes = leggi_byte(ser, 4)
    size = int.from_bytes(size_bytes, 'little')
    return width , height , size

def creazione_seriale(PORTA, BAUDRATE):
    ser = serial.Serial(PORTA , baudrate=BAUDRATE)
    return ser

def leggi_byte(ser, n):
    data = b""
    while len(data) < n:
        chunk = ser.read(n - len(data))
        if not chunk:
            raise TimeoutError("Timeout leggendo dalla seriale")
        data += chunk
    return data

def attesa_sincronizzazione(ser):
    sync = b""
    while sync != b"FRM0":
        b1 = ser.read(1)
        if not b1:
            raise TimeoutError("Timeout aspettando FRM0")
        sync = (sync + b1)[-4:]
    
if __name__ == "__main__":
    main()    

