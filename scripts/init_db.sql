-- Run this once to create the database before starting the app.
-- Usage: psql -U postgres -f scripts/init_db.sql

-- Create database (ignore error if already exists)
SELECT 'CREATE DATABASE hr_chatbot'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'hr_chatbot'
)\gexec

-- Connect to the new database
\c hr_chatbot

-- Enable UUID extension (optional, we use Python-generated UUIDs)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Tables are created automatically via SQLAlchemy on app startup.
-- This script only ensures the DB and extensions exist.

\echo 'Database hr_chatbot is ready.'
