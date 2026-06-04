import cv2
import numpy as np
import requests
import serial
import time
import math

# ==============================================================================
# --- BAĞLANTI VE PORT AYARLARI ---
# ==============================================================================
esp32_ip = '10.39.32.241'                     # ESP32-CAM kartının mevcut IP adresi
url = f'http://{esp32_ip}:81/stream'          # Video akışının çekileceği stream adresi
control_url = f'http://{esp32_ip}/control'    # Flaş kontrolü için ana HTTP adresi
arduino_port = 'COM7'                         # Arduino Uno'nun bağlı olduğu port

# ==============================================================================
# --- SİSTEM DURUM DEĞİŞKENLERİ ---
# ==============================================================================
analiz_aktif = True     # 'a' tuşu ile kontrol edilir (Otonom analiz Açık/Kapalı)
flas_aktif = False      # 'f' tuşu ile kontrol edilir (ESP32 Flaş Açık/Kapalı)
manuel_alarm = False    # 's' tuşu ile kontrol edilir (Manuel test sireni)

fps_baslangic_zamani = 0  # FPS hesaplama için zaman tutucu
fps = 0                   # Anlık kare hızı değeri

print("=== [KIRMIZI YUVARLAK NESNE ANALİZ MERKEZİ BAŞLATILIYOR] ===")

# ==============================================================================
# 1. ADIM: ARDUINO SERİ PORT BAĞLANTI KONTROLÜ
# ==============================================================================
try:
    # 9600 baud rate hızında Arduino bağlantısını başlatıyoruz
    arduino = serial.Serial(arduino_port, 9600, timeout=1)
    print(f"[BAĞLANTI LOG]: Arduino ({arduino_port}) başarıyla bağlandı.")
    time.sleep(2)  # Seri port açılırken Arduino'nun reset atmasını bekliyoruz
except Exception as e:
    print(f"[SİSTEM UYARISI]: Arduino bulunamadı! Alarm sinyalleri gönderilemeyecek. Detay: {e}")
    arduino = None

# ==============================================================================
# FONKSİYON: ESP32-CAM FLAŞ (LED) KONTROL MEKANİZMASI
# ==============================================================================
def flas_degistir(durum):
    """ESP32 üzerindeki dahili flaş LED'ini HTTP istekleri ile açar veya kapatır."""
    try:
        # Flaş açıksa parlaklık değerini maksimum (255), kapalıysa (0) yapıyoruz
        val = 255 if durum else 0
        requests.get(f"{control_url}?var=led_intensity&val={val}", timeout=2)
        print(f"[KOMUT LOG]: Flaş durumu güncellendi -> {'AÇIK' if durum else 'KAPALI'}")
    except Exception as e:
        print(f"[HATA LOG]: Flaş komutu ESP32'ye ulaştırılamadı! Detay: {e}")

# ==============================================================================
# 2. ADIM: VİDEO AKIŞ DÖNGÜSÜ VE ANALİZ
# ==============================================================================
print(f"[AĞ LOG]: ESP32-CAM canlı yayını bekleniyor: {url}")
bytes_data = bytes()

while True:
    try:
        # ESP32-CAM'den gelen ham HTTP video paketlerini alıyoruz
        r = requests.get(url, stream=True, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        
        for chunk in r.iter_content(chunk_size=1024):
            bytes_data += chunk
            a = bytes_data.find(b'\xff\xd8') # JPEG formatının başlangıç kodu
            b = bytes_data.find(b'\xff\xd9') # JPEG formatının bitiş kodu
            
            if a != -1 and b != -1:
                jpg = bytes_data[a:b+2]
                bytes_data = bytes_data[b+2:]
                
                if not jpg: continue
                img_array = np.frombuffer(jpg, dtype=np.uint8)
                if img_array.size > 0:
                    frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                else: continue

                if frame is not None:
                    # --- PERFORMANCE: FPS HESAPLAMA ---
                    mevcut_zaman = time.time()
                    fps = 1 / (mevcut_zaman - fps_baslangic_zamani)
                    fps_baslangic_zamani = mevcut_zaman

                    tespit_edildi = False
                    dairelik_orani = 0

                    # --- GÖRÜNTÜ ANALİZ MODÜLÜ ---
                    if analiz_aktif:
                        # Görüntüyü renk ayrımı yapabilmek için HSV formatına çeviriyoruz
                        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                        
                        # Kırmızı renk için alt ve üst renk eşik sınırları
                        alt_kirmizi = np.array([0, 120, 70])
                        ust_kirmizi = np.array([10, 255, 255])
                        maske = cv2.inRange(hsv, alt_kirmizi, ust_kirmizi)
                        
                        # Karıncalanmayı ve küçük parazitleri engellemek için medyofiltre uyguluyoruz
                        maske = cv2.medianBlur(maske, 5)
                        
                        # Maskelenmiş alandaki kırmızı lekelerin sınırlarını (konturlarını) buluyoruz
                        konturlar, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        
                        for k in konturlar:
                            alan = cv2.contourArea(k)       # Kırmızı lekenin piksel alanı
                            cevre = cv2.arcLength(k, True)  # Kırmızı lekenin çevre uzunluğu
                            
                            # Çok küçük lekeleri (parazitleri) engellemek için 1000px sınırı koyuyoruz
                            if alan > 1000 and cevre > 0:
                                # DAİRESELLİK FORMÜLÜ: 4 * pi * Alan / (Çevre^2)
                                # Nesne kusursuz bir yuvarlaksa bu matematiksel oran 1.0 çıkar.
                                dairesellik = (4 * math.pi * alan) / (cevre ** 2)
                                
                                # Eğer nesnenin şekli %70 ve üzeri oranda yuvarlaksa (0.7 eşiği)
                                if dairesellik > 0.7:
                                    # Yuvarlak nesnenin merkez noktasını ve yarıçapını buluyoruz
                                    (x, y), yaricap = cv2.minEnclosingCircle(k)
                                    merkez = (int(x), int(y))
                                    yaricap = int(yaricap)
                                    
                                    # Geometrik işaretleme: Hedefin etrafına YEŞİL bir ÇEMBER çiz
                                    cv2.circle(frame, merkez, yaricap, (0, 255, 0), 2)
                                    # Tam merkez noktasına KIRMIZI bir nişangah noktası koy
                                    cv2.circle(frame, merkez, 3, (0, 0, 255), -1)
                                    
                                    tespit_edildi = True
                                    dairelik_orani = dairesellik
                                    
                                    # Ekranda hedefin hemen üzerine yuvarlaklık yüzdesini yaz
                                    cv2.putText(frame, f"YUVARLAK: %{int(dairelik_orani*100)}", 
                                                (merkez[0] - 50, merkez[1] - yaricap - 10), 
                                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                                    break # İlk ve en büyük dairesel hedefi kilitleyip döngüden çıkıyoruz

                    # --- ARDUINO ALARM YÖNETİMİ ---
                    # Manuel alarm verilmişse VEYA otonom olarak kırmızı yuvarlak hedef bulunmuşsa
                    if arduino:
                        if manuel_alarm or (analiz_aktif and tespit_edildi):
                            arduino.write(b'1') # Arduino'ya alarmı çal emri ('1') gönderiliyor
                        else:
                            arduino.write(b'0') # Arduino'ya alarmı sustur emri ('0') gönderiliyor

                    # ==========================================================
                    # --- OSD: EKRAN ÜSTÜ PANEL GÖSTERGELERİ (DASHBOARD) ---
                    # ==========================================================
                    # 1. Sol Üst Bilgiler (FPS, Analiz Modu, Flaş Modu)
                    cv2.putText(frame, f"FPS: {int(fps)}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
                    
                    analiz_metni = "ANALIZ: OTOMATIK YUVARLAK" if analiz_aktif else "ANALIZ: MANUEL (KAPALI)"
                    cv2.putText(frame, analiz_metni, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

                    flas_metni = "FLAS: ACIK" if flas_aktif else "FLAS: KAPALI"
                    cv2.putText(frame, flas_metni, (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

                    # 2. Sağ Üst Dinamik Sistem Durumu Göstergesi
                    if manuel_alarm:
                        cv2.putText(frame, "SISTEM: MANUEL ALARM!", (frame.shape[1] - 220, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                    elif analiz_aktif and tespit_edildi:
                        cv2.putText(frame, "SISTEM: HEDEF KILIT!", (frame.shape[1] - 210, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                    else:
                        cv2.putText(frame, "SISTEM: GUVENLI", (frame.shape[1] - 160, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

                    # 3. Alt Kısım Kullanım Kılavuzu Göstergesi
                    cv2.putText(frame, "[F]:Flas Ac/Kapat  [A]:Analiz Ac/Kapat  [S]:Siren Test  [Q]:Cikis", 
                                (10, frame.shape[0] - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

                    # Görsel paneli ekranda gösteriyoruz
                    cv2.imshow("Robot Gozu - Guvenlik Komuta Merkezi", frame)
                
                # ==============================================================
                # --- MANUEL KULLANICI KONTROLLERİ (KLAVYE DİNLEME) ---
                # ==============================================================
                key = cv2.waitKey(1) & 0xFF
                
                if key == ord('q'): # GÜVENLİ ÇIKIŞ
                    print("[SİSTEM LOG]: Kullanıcı çıkış isteği gönderdi. Kapatılıyor...")
                    if flas_aktif: flas_degistir(False) # Kapatırken flaş açıksa söndürür
                    break
                    
                elif key == ord('f'): # MANUEL FLAŞ KONTROLÜ
                    flas_aktif = not flas_aktif
                    flas_degistir(flas_aktif)
                    
                elif key == ord('a'): # MANUEL ANALİZ KONTROLÜ
                    analiz_aktif = not analiz_aktif
                    print(f"[SİSTEM LOG]: Kamera otonom analizi -> {'AKTİFLEŞTİRİLDİ' if analiz_aktif else 'DURDURULDU'}")
                    
                elif key == ord('s'): # MANUEL SİREN/ALARM KONTROLÜ
                    manuel_alarm = not manuel_alarm
                    print(f"[SİSTEM LOG]: Manuel alarm tetikleme -> {'AKTİF' if manuel_alarm else 'PASİF'}")

        break
    except Exception as e:
        print(f"[BAĞLANTI HATASI]: ESP32-CAM akışı koptu: {e}. 2 saniye içinde yeniden bağlanılıyor...")
        time.sleep(2)
        continue

# ==============================================================================
# SİSTEM KAPANIŞ VE TEMİZLİK ADIMI
# ==============================================================================
if arduino: 
    arduino.write(b'0') # Kapatırken alarmın ötme ihtimaline karşı susturma emri gönderilir
    arduino.close()
    print("[SİSTEM LOG]: Arduino portu güvenli şekilde kapatıldı.")
    
cv2.destroyAllWindows()
print("=== [SİSTEM GÜVENLİ ŞEKİLDE KAPATILDI] ===")