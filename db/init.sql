-- Schema for MySQL 5.6.5+ / 5.7 / 8.x (equivalent to db/schema.ts).
-- Apply with `npm run db:init` (no mysql client needed). Safe to re-run.

CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(191) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  display_name VARCHAR(255) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS strategies (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  name VARCHAR(80) NOT NULL,
  slug VARCHAR(60) NOT NULL UNIQUE,
  branch VARCHAR(120) NOT NULL,
  hypothesis TEXT NOT NULL,
  spec MEDIUMTEXT NOT NULL,
  code MEDIUMTEXT NOT NULL,
  config TEXT NOT NULL,
  status ENUM('draft','testing','passed','failed','submitted','merged','archived') NOT NULL DEFAULT 'draft',
  committed_hash VARCHAR(64) NOT NULL DEFAULT '',
  commit_sha VARCHAR(40) NOT NULL DEFAULT '',
  committed_at DATETIME NULL,
  gate_status VARCHAR(20) NOT NULL DEFAULT '',
  gate_report MEDIUMTEXT NULL,
  run_id VARCHAR(30) NOT NULL DEFAULT '',
  run_url VARCHAR(300) NOT NULL DEFAULT '',
  last_checked_at DATETIME NULL,
  pr_number INT NULL,
  pr_url VARCHAR(300) NOT NULL DEFAULT '',
  error VARCHAR(500) NOT NULL DEFAULT '',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX strategies_user_idx (user_id, updated_at),
  INDEX strategies_status_idx (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ai_calls (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  kind VARCHAR(20) NOT NULL,
  model VARCHAR(120) NOT NULL DEFAULT '',
  ok TINYINT NOT NULL DEFAULT 1,
  tokens INT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX ai_calls_user_idx (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
