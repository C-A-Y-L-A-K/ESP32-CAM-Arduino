import cv2
import numpy as np
import requests
import threading
import time
import math

# ==============================================================================
# --- BAĞLANTI VE AYARLAR ---
# ==============================================================================
esp32_ip    = '10.39.32.241'                      # ESP32-CAM kartının mevcut IP adresi
url         = f'http://{esp32_ip}:81/stream'      # Video akışının çekileceği stream adresi
control_url = f'http://{esp32_ip}/control'        # Flaş kontrolü için HTTP adresi
alarm_url   = f'http://{esp32_ip}/alarm'          # Alarm kontrolü için HTTP adresi
servo_url   = f'http://{esp32_ip}/servo'          # Manuel servo kontrolü için HTTP adresi

# ==============================================================================
# --- SİSTEM DURUM DEĞİŞKENLERİ ---
# ==============================================================================
analiz_aktif  = True   # 'a' tuşu ile kontrol edilir (Otonom analiz Açık/Kapalı)
flas_aktif    = False  # 'f' tuşu ile kontrol edilir (ESP32 Flaş Açık/Kapalı)
manuel_alarm  = False  # 's' tuşu ile kontrol edilir (Manuel test sireni)

# Servo manuel kontrol değişkenleri
servo_pos     = 1500   # Başlangıç konumu: merkez (1500µs = 90°)
SERVO_MIN     = 1000   # Sol sınır (~45°)
SERVO_MAX     = 2000   # Sağ sınır (~135°)
SERVO_ADIM    = 100    # Her tuş basışında kaç µs kayacak

fps_baslangic_zamani = 0  # FPS hesaplama için zaman tutucu
fps = 0                   # Anlık kare hızı değeri

# Alarm HTTP isteğinin video döngüsünü bloklamasını engellemek için son durum takibi
son_alarm_durumu = None   # None = henüz gönderilmedi, True/False = son gönderilen durum

print("=== [OTONOM GÜVENLİK BOTU - ESP32-CAM DOĞRUDAN KONTROL] ===")
print(f"[AĞ LOG]: Kamera akışı -> {url}")
print(f"[AĞ LOG]: Alarm kontrolü -> {alarm_url}")

# ==============================================================================
# FONKSİYON: ESP32-CAM FLAŞ (LED) KONTROL MEKANİZMASI
# ==============================================================================
def flas_degistir(durum):
    """ESP32 üzerindeki dahili flaş LED'ini HTTP istekleri ile açar veya kapatır."""
    try:
        val = 255 if durum else 0
        requests.get(f"{control_url}?var=led_intensity&val={val}", timeout=2)
        print(f"[KOMUT LOG]: Flaş durumu güncellendi -> {'AÇIK' if durum else 'KAPALI'}")
    except Exception as e:
        print(f"[HATA LOG]: Flaş komutu ESP32'ye ulaştırılamadı! Detay: {e}")

# ==============================================================================
# FONKSİYON: ESP32'YE HTTP ÜZERINDEN ALARM KOMUTU GÖNDER (Arduino Yok!)
# ==============================================================================
def alarm_gonder(durum):
    """
    ESP32'deki /alarm uç noktasına HTTP GET isteği gönderir.
    durum=True  -> Buzzer çal, Servo hareket ettir
    durum=False -> Buzzer sus, Servo merkeze dön
    Bu fonksiyon ayrı bir thread'de çalışır, video döngüsünü bloklamaz.
    """
    try:
        state_val = 1 if durum else 0
        requests.get(f"{alarm_url}?state={state_val}", timeout=2)
        print(f"[ALARM LOG]: ESP32'ye alarm komutu gönderildi -> state={state_val}")
    except Exception as e:
        print(f"[HATA LOG]: Alarm komutu ESP32'ye ulaştırılamadı! Detay: {e}")

def alarm_gonder_async(durum):
    """alarm_gonder fonksiyonunu arka planda ayrı thread ile çağırır."""
    t = threading.Thread(target=alarm_gonder, args=(durum,), daemon=True)
    t.start()

# ==============================================================================
# FONKSİYON: ESP32'YE HTTP ÜZERINDEN SERVO KOMUTU GÖNDER
# ==============================================================================
def servo_gonder(pos_us):
    """
    ESP32'deki /servo?pos=<us> uç noktasına HTTP GET isteği gönderir.
    Alarm aktifken ESP32 komutu zaten yoksayar.
    """
    try:
        requests.get(f"{servo_url}?pos={pos_us}", timeout=2)
    except Exception as e:
        print(f"[HATA LOG]: Servo komutu gönderilemedi! Detay: {e}")

def servo_gonder_async(pos_us):
    """servo_gonder fonksiyonunu arka planda ayrı thread ile çağırır."""
    t = threading.Thread(target=servo_gonder, args=(pos_us,), daemon=True)
    t.start()

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
                    # --- FPS HESAPLAMA ---
                    mevcut_zaman = time.time()
                    if fps_baslangic_zamani > 0:
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
                        
                        # Karıncalanmayı ve küçük parazitleri engellemek için medyan filtre
                        maske = cv2.medianBlur(maske, 5)
                        
                        # Maskelenmiş alandaki kırmızı lekelerin konturlarını buluyoruz
                        konturlar, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        
                        for k in konturlar:
                            alan  = cv2.contourArea(k)
                            cevre = cv2.arcLength(k, True)
                            
                            # Çok küçük lekeleri (parazitleri) engellemek için 1000px sınırı
                            if alan > 1000 and cevre > 0:
                                # DAİRESELLİK FORMÜLÜ: 4 * pi * Alan / (Çevre^2)
                                dairesellik = (4 * math.pi * alan) / (cevre ** 2)
                                
                                # Nesnenin şekli %70 ve üzeri oranda yuvarlaksa
                                if dairesellik > 0.7:
                                    (x, y), yaricap = cv2.minEnclosingCircle(k)
                                    merkez  = (int(x), int(y))
                                    yaricap = int(yaricap)
                                    
                                    # Hedefin etrafına YEŞİL çember çiz
                                    cv2.circle(frame, merkez, yaricap, (0, 255, 0), 2)
                                    # Merkez noktasına KIRMIZI nişangah noktası koy
                                    cv2.circle(frame, merkez, 3, (0, 0, 255), -1)
                                    
                                    tespit_edildi  = True
                                    dairelik_orani = dairesellik
                                    
                                    # Hedefin üzerine yuvarlaklık yüzdesini yaz
                                    cv2.putText(frame, f"YUVARLAK: %{int(dairelik_orani*100)}", 
                                                (merkez[0] - 50, merkez[1] - yaricap - 10), 
                                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                                    break # İlk dairesel hedefi kilitleyip döngüden çık

                    # =========================================================
                    # --- ESP32 HTTP ALARM YÖNETİMİ (Arduino Yok!) ---
                    # Alarm durumu değiştiyse ESP32'ye HTTP isteği gönder.
                    # Her karede değil, sadece durum değiştiğinde gönderilir
                    # (gereksiz HTTP isteklerini önlemek için).
                    # =========================================================
                    alarm_isteniyor = manuel_alarm or (analiz_aktif and tespit_edildi)

                    if alarm_isteniyor != son_alarm_durumu:
                        son_alarm_durumu = alarm_isteniyor
                        alarm_gonder_async(alarm_isteniyor)

                    # ==========================================================
                    # --- OSD: EKRAN ÜSTÜ PANEL GÖSTERGELERİ ---
                    # ==========================================================
                    # 1. Sol Üst Bilgiler
                    cv2.putText(frame, f"FPS: {int(fps)}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
                    
                    analiz_metni = "ANALIZ: OTOMATIK YUVARLAK" if analiz_aktif else "ANALIZ: MANUEL (KAPALI)"
                    cv2.putText(frame, analiz_metni, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

                    flas_metni = "FLAS: ACIK" if flas_aktif else "FLAS: KAPALI"
                    cv2.putText(frame, flas_metni, (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

                    # ESP32 alarm iletişim durumunu göster
                    alarm_bagli_metni = f"ALARM: HTTP -> {esp32_ip}"
                    cv2.putText(frame, alarm_bagli_metni, (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

                    # Servo pozisyon göstergesi: yüzde olarak göster
                    servo_yuzde = int((servo_pos - SERVO_MIN) / (SERVO_MAX - SERVO_MIN) * 100)
                    servo_metni = f"SERVO: {'<<<' if servo_yuzde < 40 else ('>>>' if servo_yuzde > 60 else 'MRK')} %{servo_yuzde}"
                    renk_servo  = (0, 165, 255) if servo_yuzde != 50 else (0, 255, 200)
                    cv2.putText(frame, servo_metni, (10, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.4, renk_servo, 1)

                    # 2. Sağ Üst Dinamik Sistem Durumu
                    if manuel_alarm:
                        cv2.putText(frame, "SISTEM: MANUEL ALARM!", (frame.shape[1] - 230, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                    elif analiz_aktif and tespit_edildi:
                        cv2.putText(frame, "SISTEM: HEDEF KILIT!", (frame.shape[1] - 210, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                    else:
                        cv2.putText(frame, "SISTEM: GUVENLI", (frame.shape[1] - 160, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

                    # 3. Alt Kullanım Kılavuzu
                    cv2.putText(frame, "[F]:Flas  [A]:Analiz  [S]:Siren  [Z]:Saga  [X]:Sola  [Q]:Cikis", 
                                (10, frame.shape[0] - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

                    # Görsel paneli ekranda göster
                    cv2.imshow("Robot Gozu - Guvenlik Komuta Merkezi", frame)
                
                # ==============================================================
                # --- MANUEL KULLANICI KONTROLLERİ (KLAVYE DİNLEME) ---
                # ==============================================================
                key = cv2.waitKey(1) & 0xFF
                
                if key == ord('q'): # GÜVENLİ ÇIKIŞ
                    print("[SİSTEM LOG]: Kullanıcı çıkış isteği gönderdi. Kapatılıyor...")
                    if flas_aktif: flas_degistir(False)
                    alarm_gonder(False)
                    break
                    
                elif key == ord('f'): # MANUEL FLAŞ KONTROLÜ
                    flas_aktif = not flas_aktif
                    flas_degistir(flas_aktif)
                    
                elif key == ord('a'): # MANUEL ANALİZ KONTROLÜ
                    analiz_aktif = not analiz_aktif
                    print(f"[SİSTEM LOG]: Otonom analiz -> {'AKTİFLEŞTİRİLDİ' if analiz_aktif else 'DURDURULDU'}")
                    
                elif key == ord('s'): # MANUEL SİREN/ALARM KONTROLÜ
                    manuel_alarm = not manuel_alarm
                    print(f"[SİSTEM LOG]: Manuel alarm -> {'AKTİF' if manuel_alarm else 'PASİF'}")

                elif key == ord('z'): # SERVO SAGA DÖNDÜR
                    servo_pos = min(servo_pos + SERVO_ADIM, SERVO_MAX)
                    print(f"[SERVO LOG]: Sağa -> {servo_pos}µs")
                    servo_gonder_async(servo_pos)

                elif key == ord('x'): # SERVO SOLA DÖNDÜR
                    servo_pos = max(servo_pos - SERVO_ADIM, SERVO_MIN)
                    print(f"[SERVO LOG]: Sola -> {servo_pos}µs")
                    servo_gonder_async(servo_pos)

        break
    except Exception as e:
        print(f"[BAĞLANTI HATASI]: ESP32-CAM akışı koptu: {e}. 2 saniye içinde yeniden bağlanılıyor...")
        time.sleep(2)
        continue

# ==============================================================================
# SİSTEM KAPANIŞ VE TEMİZLİK ADIMI
# ==============================================================================
# Arduino yok - Kapanış işlemleri sadece HTTP üzerinden yapılıyor
alarm_gonder(False)  # ESP32'ye son bir "alarmı kapat" komutu gönder
print("[SİSTEM LOG]: ESP32'ye kapatma alarmı gönderildi.")

cv2.destroyAllWindows()
print("=== [SİSTEM GÜVENLİ ŞEKİLDE KAPATILDI] ===")