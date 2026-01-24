// Pin Maps:

// A4988 stepper driver
const int dirPin = 2;
const int stepPin = 3;
const int enablePin = 4;

// Actuators
const int SOLENOID_PIN = 5;
const int MAGNET_PIN   = 6;

// L298N DC motor driver
const int IN1 = 8;
const int IN2 = 9;
const int ENA = 10;

// Logic Configuration
const bool MAGNET_ACTIVE_LOW = true;

// Motion Parameters
const unsigned int stepHighUs = 2000;
const unsigned int stepLowUs  = 2000;

const int motorSpeed = 120;
const int stepAmount = 50;

// Output State
bool solenoidState = false;
bool magnetState = false;

// Serial Command Buffer
static const unsigned int CMD_BUF_LEN = 64;
char cmdBuf[CMD_BUF_LEN];
unsigned int cmdLen = 0;

// Output Apply
void applyActuators() {
  digitalWrite(SOLENOID_PIN, solenoidState ? HIGH : LOW);

  if (magnetState) {
    digitalWrite(MAGNET_PIN, MAGNET_ACTIVE_LOW ? LOW : HIGH);
  } else {
    digitalWrite(MAGNET_PIN, MAGNET_ACTIVE_LOW ? HIGH : LOW);
  }
}

// DC Motor
void driveLeft() {
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, HIGH);
  analogWrite(ENA, motorSpeed);
}

void driveRight() {
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  analogWrite(ENA, motorSpeed);
}

void stopDC() {
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);
  analogWrite(ENA, 0);
}

// Stepper
void stepperMove(bool up, unsigned long steps) {
  digitalWrite(dirPin, up ? HIGH : LOW);

  for (unsigned long i = 0; i < steps; i++) {
    digitalWrite(stepPin, HIGH);
    delayMicroseconds(stepHighUs);
    digitalWrite(stepPin, LOW);
    delayMicroseconds(stepLowUs);
  }
}

// Command Parsing
static void trimInPlace(char *s) {
  if (!s) return;

  unsigned int start = 0;
  while (s[start] == ' ' || s[start] == '\t' || s[start] == '\r' || s[start] == '\n') start++;

  unsigned int end = 0;
  while (s[end] != '\0') end++;
  while (end > start && (s[end - 1] == ' ' || s[end - 1] == '\t' || s[end - 1] == '\r' || s[end - 1] == '\n')) end--;

  unsigned int j = 0;
  for (unsigned int i = start; i < end; i++) s[j++] = s[i];
  s[j] = '\0';
}

// Command Dispatcher
void handleCommand(char *c) {
  trimInPlace(c);

  if (strcmp(c, "MOVE_LEFT") == 0) {
    driveLeft();
  }
  else if (strcmp(c, "MOVE_RIGHT") == 0) {
    driveRight();
  }
  else if (strcmp(c, "MOVE_STOP") == 0) {
    stopDC();
  }
  else if (strcmp(c, "UP") == 0) {
    stepperMove(true, stepAmount);
  }
  else if (strcmp(c, "DOWN") == 0) {
    stepperMove(false, stepAmount);
  }
  else if (strcmp(c, "SOLENOID_ON") == 0) {
    solenoidState = true;
    applyActuators();
  }
  else if (strcmp(c, "SOLENOID_OFF") == 0) {
    solenoidState = false;
    applyActuators();
  }
  else if (strcmp(c, "MAGNET_ON") == 0) {
    magnetState = true;
    applyActuators();
  }
  else if (strcmp(c, "MAGNET_OFF") == 0) {
    magnetState = false;
    applyActuators();
  }

  Serial.print("CMD: ");
  Serial.println(c);
}

// Arduino Setup
void setup() {
  Serial.begin(115200);

  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(ENA, OUTPUT);

  pinMode(dirPin, OUTPUT);
  pinMode(stepPin, OUTPUT);
  pinMode(enablePin, OUTPUT);

  pinMode(SOLENOID_PIN, OUTPUT);
  pinMode(MAGNET_PIN, OUTPUT);

  stopDC();

  digitalWrite(enablePin, LOW);
  digitalWrite(stepPin, LOW);

  solenoidState = false;
  magnetState = false;
  applyActuators();

  cmdBuf[0] = '\0';

  Serial.println("READY");
}

void loop() {
  int processed = 0;

  while (Serial.available() > 0 && processed < 128) {
    char ch = (char)Serial.read();
    processed++;

    if (ch == '\n') {
      cmdBuf[cmdLen] = '\0';
      handleCommand(cmdBuf);
      cmdLen = 0;
      cmdBuf[0] = '\0';
    } else if (ch != '\r') {
      if (cmdLen < (CMD_BUF_LEN - 1)) {
        cmdBuf[cmdLen++] = ch;
      } else {
        cmdLen = 0;
        cmdBuf[0] = '\0';
      }
    }
  }

  delay(10);
}