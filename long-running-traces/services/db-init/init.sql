-- Foo Management — Demo Schema
-- SQL Server 2022
-- Seed data for OTel tracing demo

USE master;
GO

IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = 'foo')
BEGIN
    CREATE DATABASE foo;
END
GO

USE foo;
GO

-- ─── Tables ───────────────────────────────────────────────────────────────────

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'users')
CREATE TABLE users (
    id            INT IDENTITY(1,1) PRIMARY KEY,
    username      NVARCHAR(64)  NOT NULL UNIQUE,
    password_hash NVARCHAR(256) NOT NULL,
    full_name     NVARCHAR(128) NOT NULL,
    created_at    DATETIME2     DEFAULT GETUTCDATE()
);
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'portfolios')
CREATE TABLE portfolios (
    id         INT IDENTITY(1,1) PRIMARY KEY,
    user_id    INT            NOT NULL REFERENCES users(id),
    name       NVARCHAR(128)  NOT NULL,
    aum        DECIMAL(18,2)  NOT NULL DEFAULT 0,
    currency   NCHAR(3)       NOT NULL DEFAULT 'USD',
    created_at DATETIME2      DEFAULT GETUTCDATE()
);
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'positions')
CREATE TABLE positions (
    id           INT IDENTITY(1,1) PRIMARY KEY,
    portfolio_id INT           NOT NULL REFERENCES portfolios(id),
    ticker       NVARCHAR(16)  NOT NULL,
    quantity     DECIMAL(18,4) NOT NULL,
    cost_basis   DECIMAL(18,4) NOT NULL,
    market_value DECIMAL(18,2) NOT NULL,
    updated_at   DATETIME2     DEFAULT GETUTCDATE()
);
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'trades')
CREATE TABLE trades (
    id           INT IDENTITY(1,1) PRIMARY KEY,
    portfolio_id INT           NOT NULL REFERENCES portfolios(id),
    ticker       NVARCHAR(16)  NOT NULL,
    quantity     DECIMAL(18,4) NOT NULL,
    price        DECIMAL(18,4) NOT NULL,
    side         NCHAR(4)      NOT NULL CHECK (side IN ('BUY ','SELL')),
    status       NVARCHAR(16)  NOT NULL DEFAULT 'pending'
                               CHECK (status IN ('pending','validated','settled','failed')),
    trade_date   DATETIME2     DEFAULT GETUTCDATE()
);
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'batch_reports')
CREATE TABLE batch_reports (
    id           INT IDENTITY(1,1) PRIMARY KEY,
    run_date     DATETIME2     DEFAULT GETUTCDATE(),
    portfolio_id INT           REFERENCES portfolios(id),
    total_pnl    DECIMAL(18,2) NOT NULL,
    trade_count  INT           NOT NULL,
    status       NVARCHAR(16)  NOT NULL DEFAULT 'complete'
);
GO

-- ─── Seed data ────────────────────────────────────────────────────────────────

-- Users  (password = bcrypt of 'demo123' for demo / FooAdmin!1 for others)
-- Using plain SHA2 hash for simplicity in demo (not production-grade)
IF NOT EXISTS (SELECT 1 FROM users WHERE username = 'demo')
BEGIN
    -- Hashes are SHA256: demo=demo123, jsmith=Smith!2024, mwilson=Wilson!2024
    INSERT INTO users (username, password_hash, full_name) VALUES
        ('demo',    'd3ad9315b7be5dd53b31a273b3b3aba5defe700808305aa16a3062b76658a791', 'Demo User'),
        ('jsmith',  'f2ca1bb6c7e907d06dafe4687e579fce76b37e4e93b7605022da52e6ccc26fd2', 'John Smith'),
        ('mwilson', '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08', 'Margaret Wilson');
END
GO

-- Portfolios
IF NOT EXISTS (SELECT 1 FROM portfolios WHERE name = 'Foo Capital Fund I')
BEGIN
    INSERT INTO portfolios (user_id, name, aum, currency)
    SELECT id, 'Foo Capital Fund I', 245000000.00, 'USD' FROM users WHERE username = 'demo'
    UNION ALL
    SELECT id, 'Foo Credit Opportunities', 118500000.00, 'USD' FROM users WHERE username = 'jsmith';
END
GO

-- Positions — Portfolio 1
IF NOT EXISTS (SELECT 1 FROM positions WHERE ticker = 'MSFT' AND portfolio_id = 1)
BEGIN
    INSERT INTO positions (portfolio_id, ticker, quantity, cost_basis, market_value) VALUES
        (1, 'MSFT',  12500.0000, 380.2500, 5031250.00),
        (1, 'AAPL',  18000.0000, 175.1000, 3240000.00),
        (1, 'JPM',   22000.0000,  198.4000, 4488000.00),
        (1, 'GS',     8500.0000,  452.7500, 3941250.00),
        (1, 'BLK',    3200.0000,  852.3000, 2747200.00),
        (1, 'BX',    14000.0000,  125.6500, 1778750.00),
        -- Portfolio 2
        (2, 'KKR',   25000.0000,   98.4500, 2475000.00),
        (2, 'APO',   19500.0000,  112.3000, 2194875.00),
        (2, 'FOO',  31000.0000,   89.7500, 2839500.00),
        (2, 'CG',    28000.0000,   58.9000, 1652000.00);
END
GO

-- Trades — mix of pending and settled
IF NOT EXISTS (SELECT 1 FROM trades WHERE portfolio_id = 1 AND ticker = 'MSFT' AND status = 'pending')
BEGIN
    INSERT INTO trades (portfolio_id, ticker, quantity, price, side, status, trade_date) VALUES
        (1, 'MSFT',  500.0000, 402.5000, 'BUY ', 'pending',   DATEADD(minute, -30, GETUTCDATE())),
        (1, 'AAPL', 1000.0000, 179.8000, 'BUY ', 'pending',   DATEADD(minute, -25, GETUTCDATE())),
        (1, 'GS',    200.0000, 458.1000, 'SELL', 'pending',   DATEADD(minute, -20, GETUTCDATE())),
        (1, 'JPM',   750.0000, 201.3500, 'BUY ', 'validated', DATEADD(minute, -45, GETUTCDATE())),
        (1, 'BLK',   100.0000, 865.0000, 'BUY ', 'validated', DATEADD(minute, -50, GETUTCDATE())),
        (1, 'MSFT',  300.0000, 395.2000, 'SELL', 'settled',   DATEADD(hour,   -2,  GETUTCDATE())),
        (1, 'BX',   2000.0000, 122.4000, 'BUY ', 'settled',   DATEADD(hour,   -3,  GETUTCDATE())),
        (2, 'KKR',  1500.0000,  99.8000, 'BUY ', 'pending',   DATEADD(minute, -15, GETUTCDATE())),
        (2, 'FOO', 2000.0000,  91.2500, 'BUY ', 'pending',   DATEADD(minute, -10, GETUTCDATE())),
        (2, 'APO',   800.0000, 115.6000, 'SELL', 'pending',   DATEADD(minute,  -5, GETUTCDATE())),
        (2, 'CG',   3000.0000,  59.7500, 'BUY ', 'validated', DATEADD(hour,   -1,  GETUTCDATE())),
        (2, 'KKR',   500.0000,  97.3000, 'SELL', 'settled',   DATEADD(hour,   -4,  GETUTCDATE())),
        (1, 'AAPL',  500.0000, 177.2000, 'SELL', 'settled',   DATEADD(hour,   -5,  GETUTCDATE())),
        (1, 'JPM',   250.0000, 199.5000, 'BUY ', 'settled',   DATEADD(hour,   -6,  GETUTCDATE())),
        (2, 'FOO', 1000.0000,  88.9000, 'BUY ', 'settled',   DATEADD(hour,   -7,  GETUTCDATE())),
        (2, 'APO',  1200.0000, 110.4000, 'BUY ', 'settled',   DATEADD(hour,   -8,  GETUTCDATE())),
        (1, 'GS',    150.0000, 445.0000, 'BUY ', 'settled',   DATEADD(hour,   -9,  GETUTCDATE())),
        (1, 'BLK',    50.0000, 840.0000, 'SELL', 'settled',   DATEADD(hour,  -10,  GETUTCDATE())),
        (2, 'CG',   2000.0000,  57.8000, 'SELL', 'settled',   DATEADD(hour,  -11,  GETUTCDATE())),
        (2, 'KKR',  1000.0000, 100.2000, 'BUY ', 'settled',   DATEADD(hour,  -12,  GETUTCDATE()));
END
GO
