-- =====================================================================
-- Online Learning Analytics & Student Engagement Prediction
-- MySQL 8.0+ schema. Run in MySQL Workbench (File > Open SQL Script > Execute).
-- The six required tables are: users, courses, enrollments, activities,
-- assessments, engagement_predictions. One extra table (alerts) is added
-- to persist early-warning alert status (see README, "Database design").
-- =====================================================================
CREATE DATABASE IF NOT EXISTS student_engagement_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE student_engagement_db1;

DROP TABLE IF EXISTS alerts;
DROP TABLE IF EXISTS engagement_predictions;
DROP TABLE IF EXISTS assessments;
DROP TABLE IF EXISTS activities;
DROP TABLE IF EXISTS enrollments;
DROP TABLE IF EXISTS courses;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
  user_id       INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name          VARCHAR(100) NOT NULL,
  email         VARCHAR(150) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role          ENUM('student','faculty') NOT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id),
  UNIQUE KEY uq_users_email (email),
  KEY idx_users_role (role)
) ENGINE=InnoDB;

CREATE TABLE courses (
  course_id   INT UNSIGNED NOT NULL AUTO_INCREMENT,
  course_name VARCHAR(150) NOT NULL,
  faculty_id  INT UNSIGNED NOT NULL,
  semester    VARCHAR(30) NOT NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (course_id),
  UNIQUE KEY uq_course_name (course_name),
  KEY idx_courses_faculty (faculty_id),
  CONSTRAINT fk_courses_faculty FOREIGN KEY (faculty_id) REFERENCES users (user_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE enrollments (
  enrollment_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  course_id     INT UNSIGNED NOT NULL,
  student_id    INT UNSIGNED NOT NULL,
  enrolled_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (enrollment_id),
  UNIQUE KEY uq_enrollment (course_id, student_id),
  KEY idx_enroll_student (student_id),
  CONSTRAINT fk_enroll_course  FOREIGN KEY (course_id)  REFERENCES courses (course_id) ON DELETE RESTRICT,
  CONSTRAINT fk_enroll_student FOREIGN KEY (student_id) REFERENCES users (user_id)     ON DELETE RESTRICT
) ENGINE=InnoDB;

-- duration is in MINUTES. source separates manual demo/typed records from
-- CSV imports and genuinely system-captured events (e.g. real logins).
CREATE TABLE activities (
  activity_id   INT UNSIGNED NOT NULL AUTO_INCREMENT,
  student_id    INT UNSIGNED NOT NULL,
  course_id     INT UNSIGNED NOT NULL,
  activity_type ENUM('login','video','material','study_session') NOT NULL,
  duration      INT UNSIGNED NOT NULL DEFAULT 0,
  activity_time DATETIME NOT NULL,
  source        ENUM('manual','csv_import','system') NOT NULL DEFAULT 'manual',
  PRIMARY KEY (activity_id),
  UNIQUE KEY uq_activity (student_id, course_id, activity_type, activity_time),
  KEY idx_act_student_time (student_id, activity_time),
  KEY idx_act_course_time (course_id, activity_time),
  CONSTRAINT chk_act_duration CHECK (duration BETWEEN 0 AND 1440),
  CONSTRAINT fk_act_student FOREIGN KEY (student_id) REFERENCES users (user_id)     ON DELETE RESTRICT,
  CONSTRAINT fk_act_course  FOREIGN KEY (course_id)  REFERENCES courses (course_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- score is a percentage-style value (0..100 by default, validated in the app against
-- ASSESSMENT_MAX_SCORE). due_at / submitted_at are optional and give assignment delay.
CREATE TABLE assessments (
  assessment_id   INT UNSIGNED NOT NULL AUTO_INCREMENT,
  student_id      INT UNSIGNED NOT NULL,
  course_id       INT UNSIGNED NOT NULL,
  score           DECIMAL(5,2) NOT NULL,
  assessment_type ENUM('quiz','assignment') NOT NULL,
  title           VARCHAR(150) NOT NULL,
  due_at          DATETIME NULL,
  submitted_at    DATETIME NULL,
  assessed_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (assessment_id),
  UNIQUE KEY uq_assessment (student_id, course_id, assessment_type, title),
  KEY idx_assess_course (course_id, assessed_at),
  KEY idx_assess_student (student_id, assessed_at),
  CONSTRAINT chk_assess_score CHECK (score >= 0 AND score <= 100),
  CONSTRAINT fk_assess_student FOREIGN KEY (student_id) REFERENCES users (user_id)     ON DELETE RESTRICT,
  CONSTRAINT fk_assess_course  FOREIGN KEY (course_id)  REFERENCES courses (course_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- engagement_score is 0..100. method = 'ml_model' or 'rule_based_baseline'.
CREATE TABLE engagement_predictions (
  prediction_id    INT UNSIGNED NOT NULL AUTO_INCREMENT,
  student_id       INT UNSIGNED NOT NULL,
  course_id        INT UNSIGNED NOT NULL,
  engagement_score DECIMAL(5,2) NOT NULL,
  risk_level       ENUM('low','medium','high') NOT NULL,
  predicted_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  method           VARCHAR(30) NOT NULL DEFAULT 'ml_model',
  model_version    VARCHAR(40) NULL,
  features_json    TEXT NULL,
  PRIMARY KEY (prediction_id),
  KEY idx_pred_student_course (student_id, course_id, predicted_at),
  KEY idx_pred_risk (risk_level),
  CONSTRAINT chk_pred_score CHECK (engagement_score BETWEEN 0 AND 100),
  CONSTRAINT fk_pred_student FOREIGN KEY (student_id) REFERENCES users (user_id)     ON DELETE RESTRICT,
  CONSTRAINT fk_pred_course  FOREIGN KEY (course_id)  REFERENCES courses (course_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- Extra table (genuinely needed): early-warning alerts with persistent status.
CREATE TABLE alerts (
  alert_id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  student_id       INT UNSIGNED NOT NULL,
  course_id        INT UNSIGNED NOT NULL,
  prediction_id    INT UNSIGNED NULL,
  engagement_score DECIMAL(5,2) NOT NULL,
  risk_level       ENUM('low','medium','high') NOT NULL,
  reason           VARCHAR(500) NOT NULL,
  suggested_action VARCHAR(500) NOT NULL,
  status           ENUM('open','acknowledged','resolved') NOT NULL DEFAULT 'open',
  created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (alert_id),
  KEY idx_alert_status (status, created_at),
  KEY idx_alert_pair (student_id, course_id, status),
  CONSTRAINT fk_alert_student FOREIGN KEY (student_id)    REFERENCES users (user_id)                   ON DELETE RESTRICT,
  CONSTRAINT fk_alert_course  FOREIGN KEY (course_id)     REFERENCES courses (course_id)               ON DELETE RESTRICT,
  CONSTRAINT fk_alert_pred    FOREIGN KEY (prediction_id) REFERENCES engagement_predictions (prediction_id) ON DELETE SET NULL
) ENGINE=InnoDB;
