#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>

// app_httpd.cpp'de tanimlanan fonksiyon ve pin sabitlerine erisim
extern void setServoPosition(uint32_t pulse_us);
#define BUZZER_PIN       14
#define SERVO_PIN        15
#define SERVO_FREQ       50
#define SERVO_RES        16
#define SERVO_CENTER_US  1500

// ===========================
// Kamera modelini board_config.h dosyasindan secin
// ===========================
#include "board_config.h"

// ===========================
// WiFi bilgilerinizi girin
// ===========================

void startCameraServer();
void setupLedFlash();

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println();

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.frame_size = FRAMESIZE_UXGA;
  config.pixel_format = PIXFORMAT_JPEG;  // for streaming
  //config.pixel_format = PIXFORMAT_RGB565; // for face detection/recognition
  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.jpeg_quality = 12;
  config.fb_count = 1;

  // Eger PSRAM entegresi varsa, daha buyuk on bellek tahsisi icin
  // UXGA cozunurlugu ve daha yuksek JPEG kalitesi ile baslat.
  if (config.pixel_format == PIXFORMAT_JPEG) {
    if (psramFound()) {
      config.jpeg_quality = 10;
      config.fb_count = 2;
      config.grab_mode = CAMERA_GRAB_LATEST;
    } else {
      // PSRAM yoksa cerceve boyutunu sinirla
      config.frame_size = FRAMESIZE_SVGA;
      config.fb_location = CAMERA_FB_IN_DRAM;
    }
  } else {
      // Yuz algilama/tanima icin en iyi secenek
      config.frame_size = FRAMESIZE_240X240;
#if CONFIG_IDF_TARGET_ESP32S3
    config.fb_count = 2;
#endif
  }

#if defined(CAMERA_MODEL_ESP_EYE)
  // NOT: Biz bu modeli kullanmiyoruz, pin 14 bizde Buzzer icin kullaniliyor.
  // pinMode(13, INPUT_PULLUP);
  // pinMode(14, INPUT_PULLUP);
#endif

  // Kamerayi baslat
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Kamera baslatilamadi, hata kodu 0x%x", err);
    return;
  }

  sensor_t *s = esp_camera_sensor_get();
  // ilk sensorler dikey olarak ters cevrilmistir ve renkler biraz doygun olabilir
  if (s->id.PID == OV3660_PID) {
    s->set_vflip(s, 1);        // geri dondur
    s->set_brightness(s, 1);   // parlakligi biraz artir
    s->set_saturation(s, -2);  // doygunlugu azalt
  }
  // daha yuksek baslangic kare hizi icin cerceve boyutunu dusur
  if (config.pixel_format == PIXFORMAT_JPEG) {
    s->set_framesize(s, FRAMESIZE_QVGA);
  }

#if defined(CAMERA_MODEL_M5STACK_WIDE) || defined(CAMERA_MODEL_M5STACK_ESP32CAM)
  s->set_vflip(s, 1);
  s->set_hmirror(s, 1);
#endif

#if defined(CAMERA_MODEL_ESP32S3_EYE)
  s->set_vflip(s, 1);
#endif

// Eger camera_pins.h icinde LED pini tanimlanmissa LED Flas'i kur
#if defined(LED_GPIO_NUM)
  setupLedFlash();
#endif

  WiFi.begin(ssid, password);
  WiFi.setSleep(false);

  Serial.print("WiFi baglaniyor");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");
  Serial.println("WiFi baglandi");

  startCameraServer();

  // ============================================================
  // --- ALARM DONANIMLARINI BASLAT ---
  // ============================================================
  // Buzzer: Standart dijital cikis (GPIO 14)
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW); // Baslangicta sustur

  // Servo: LEDC donanim PWM'i startCameraServer'DAN ONCE baslat
  // (Kamera LEDC_TIMER_0 kullaniyor; servo farkli bir timer almali)
  ledcAttach(SERVO_PIN, SERVO_FREQ, SERVO_RES);
  setServoPosition(SERVO_CENTER_US);
  delay(300);

  startCameraServer();

  // ---- BASLANGIC TARAMA SÜPÜRMESİ (sol -> sag -> merkez) ----
  Serial.println("[SERVO]: Baslangic tarama surmesi basliyor...");

  // Motor guc stabilizasyonu icin bekliyoruz
  delay(1000);

  // 1. Adim: Sol uca git ve yerles
  setServoPosition(1000);
  delay(800);

  // 2. Adim: Sol uctan (1000µs) sag uca (2000µs) sur
  // Adim: 50µs (~4.5 derece) | Gecikme: 60ms
  // Toplam: (2000-1000)/50 = 20 adim x 60ms = ~1.2 saniye
  for (uint32_t us = 1000; us <= 2000; us += 50) {
    setServoPosition(us);
    delay(60);
  }
  delay(400);

  // 3. Adim: Sag uctan merkeze (1500µs) don
  setServoPosition(SERVO_CENTER_US);
  delay(600);
  Serial.println("[SERVO]: Tarama tamamlandi. Merkez konumda bekleniyor.");

  Serial.print("Kamera Hazir! Baglanmak icin 'http://");
  Serial.print(WiFi.localIP());
  Serial.println("' adresini kullanin");
}

extern volatile bool alarm_state;
extern volatile bool auto_scan_state;

void loop() {
  if (!alarm_state && auto_scan_state) {
    Serial.println("[DEBUG-MOTOR] Tarama dongusu basliyor: Sol -> Sag");
    // Sol uçtan (500us) sağ uca (2500us) tarama
    for (uint32_t us = 500; us <= 2500; us += 50) {
      if (alarm_state || !auto_scan_state) {
        Serial.println("[DEBUG-MOTOR] Tarama kesildi!");
        break;
      }
      setServoPosition(us);
      delay(60);
    }
    
    if (!alarm_state && auto_scan_state) {
      Serial.println("[DEBUG-MOTOR] Tarama dongusu donuyor: Sag -> Sol");
      // Sağ uçtan (2500us) sol uca (500us) geri dönüş
      for (uint32_t us = 2500; us >= 500; us -= 50) {
        if (alarm_state || !auto_scan_state) {
          Serial.println("[DEBUG-MOTOR] Tarama kesildi!");
          break;
        }
        setServoPosition(us);
        delay(60);
      }
    }
  } else {
    // Alarm aktifse veya tarama kapalıysa bekle
    delay(500);
  }
}
