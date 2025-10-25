/*
 * WILDLIFE MONITOR - SUPERVISOR CODE (FINAL VERSION)
 * ---------------------------------------------------------
 * Hardware: Arduino Nano 33 IoT
 * Role: Stays on 24/7. Sends MQTT on trigger.
 * Indicators:
 * - D5 LED: Blinks fast when PIR is HIGH.
 * - D7 LED: Shows Wi-Fi/MQTT status.
 */

#include <WiFiNINA.h>
#include <ArduinoMqttClient.h>
#include <DHT.h>

// --- PIN DEFINITIONS ---
#define PIR_PIN       2   // PIR sensor pin
#define DHT_PIN       3   // DHT22 sensor pin
#define LED_PIN       5   // PIR status LED
#define VOLTAGE_PIN   A0
#define LDR_DIGITAL_PIN 6
#define NETWORK_LED_PIN 7   // <-- NEW: External Network Status LED

// --- WI-FI & MQTT CONFIGURATION ---
char ssid[] = "Param";
char pass[] = "aus@2112";
const char broker[] = "192.168.137.227"; 
int port = 1883;

// --- MQTT TOPICS ---
const char TRIGGER_TOPIC[] = "WILDLIFE/TRIGGER";

// --- GLOBAL OBJECTS ---
WiFiClient wifiClient;
MqttClient mqttClient(wifiClient);
DHT dht(DHT_PIN, DHT22);

bool motionInProgress = false; // Prevents re-triggering spam

// --- NEW: Status LED timing ---
unsigned long lastMqttBlink = 0;
const long mqttBlinkInterval = 750; // Slow blink

void setup() {
  Serial.begin(9600);
  
  pinMode(PIR_PIN, INPUT);
  pinMode(LDR_DIGITAL_PIN, INPUT); 
  pinMode(LED_PIN, OUTPUT);         // PIR LED
  pinMode(NETWORK_LED_PIN, OUTPUT); // <-- CHANGED: External Status LED
  
  dht.begin();

  Serial.println("Supervisor (Final Code) initializing...");
  
  connectAndCheck(); // Initial connection attempt
  
  Serial.println("Supervisor ready. Actively scanning...");
}

void loop() {
  // 1. Always check connections
  connectAndCheck();

  // This is essential to keep the MQTT connection alive
  mqttClient.poll();

  // 2. Check for motion
  if (digitalRead(PIR_PIN) == HIGH) {
    if (!motionInProgress) {
      // This is the FIRST moment motion is detected
      motionInProgress = true; // Set lock to prevent spam
      
      Serial.println("---------------------");
      Serial.println("Motion detected! Sending trigger.");
      
      handleMotionTrigger(); // Send the MQTT message
    }
    // This part runs as long as motion is high
    digitalWrite(LED_PIN, !digitalRead(LED_PIN)); // Fast blink
    
  } else {
    // This runs when motion is LOW
    motionInProgress = false; // Reset the lock
    digitalWrite(LED_PIN, LOW); // Turn LED OFF
  }
  
  // The 100ms delay creates the PIR LED blink speed
  delay(100); 
}

/**
 * Checks Wi-Fi and MQTT status and updates the external network LED.
 */
void connectAndCheck() {
  if (WiFi.status() != WL_CONNECTED) {
    digitalWrite(NETWORK_LED_PIN, LOW); // <-- CHANGED
    connectWiFi(); // This function blinks the LED fast
  }

  if (WiFi.status() == WL_CONNECTED && !mqttClient.connected()) {
    connectMQTT();
  }

  // Update LED status based on connections
  if (WiFi.status() == WL_CONNECTED) {
    if (mqttClient.connected()) {
      digitalWrite(NETWORK_LED_PIN, HIGH); // <-- CHANGED: Solid ON = All Good
    } else {
      // Connected to Wi-Fi, but not MQTT (Slow Blink)
      if (millis() - lastMqttBlink > mqttBlinkInterval) {
        lastMqttBlink = millis();
        digitalWrite(NETWORK_LED_PIN, !digitalRead(NETWORK_LED_PIN)); // <-- CHANGED
      }
    }
  } else {
    digitalWrite(NETWORK_LED_PIN, LOW); // <-- CHANGED: Solid OFF = No Wi-Fi
  }
}

/**
 * Reads sensors and sends the MQTT message.
 */
void handleMotionTrigger() {
  // Read sensors
  float temp = dht.readTemperature();
  float humidity = dht.readHumidity();
  int voltageRaw = analogRead(VOLTAGE_PIN); 
  int lightState = digitalRead(LDR_DIGITAL_PIN);

  if (isnan(temp) || isnan(humidity)) {
    Serial.println("Failed to read from DHT sensor!");
    temp = 0.0;
    humidity = 0.0;
  }

  String payload = "{\"temp\":" + String(temp, 1) + ",\"humidity\":" + String(humidity, 1) + ",\"battery\":" + String(voltageRaw) + ",\"light_state\":" + String(lightState) + "}";
  
  Serial.println("Sending message:");
  Serial.println(payload);
  
  mqttClient.beginMessage(TRIGGER_TOPIC, payload.length(), false, 1, false);
  mqttClient.print(payload);
  mqttClient.endMessage();
  Serial.println("Message sent.");
  Serial.println("---------------------");
}

// --- Utility Functions ---

bool connectWiFi() {
  Serial.print("Connecting to Wi-Fi...");
  WiFi.begin(ssid, pass);
  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 20) {
    // Blink external LED fast while connecting
    digitalWrite(NETWORK_LED_PIN, !digitalRead(NETWORK_LED_PIN)); // <-- CHANGED
    delay(100); // This delay controls the fast blink
    Serial.print(".");
    retries++;
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println(" FAILED.");
    digitalWrite(NETWORK_LED_PIN, LOW); // <-- CHANGED: Turn off on fail
    return false;
  }
  Serial.println(" CONNECTED.");
  digitalWrite(NETWORK_LED_PIN, HIGH); // <-- CHANGED: Solid on for now
  return true;
}

void connectMQTT() {
  Serial.print("Connecting to MQTT broker...");
  mqttClient.setId("arduino_supervisor_final");

  if (!mqttClient.connect(broker, port)) {
    Serial.print(" FAILED! Error: ");
    Serial.println(mqttClient.connectError());
  } else {
    Serial.println(" CONNECTED.");
  }
}