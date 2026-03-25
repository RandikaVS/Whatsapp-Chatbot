-- ============================================================
-- TENANTS TABLE
-- Each row represents one business client using your SaaS.
-- They each get their own WhatsApp number, bot config, and plan.
-- ============================================================

CREATE TABLE IF NOT EXISTS tenants (
    -- We use UUID as the primary key instead of a serial integer.
    -- This is safer for a SaaS because clients can't guess other
    -- clients' IDs by just incrementing a number.
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Business identity
    business_name           TEXT NOT NULL,
    email                   TEXT NOT NULL UNIQUE,

    -- This is the secret key each client uses to authenticate API calls.
    -- It also appears in their unique webhook URL:
    -- https://yourdomain.com/webhook/{api_key}
    api_key                 TEXT NOT NULL UNIQUE,

    -- WhatsApp / Meta connection details.
    -- These are filled in during Step 2 of onboarding (connect-whatsapp).
    -- They can be NULL initially because a client registers first,
    -- then connects WhatsApp separately.
    wa_phone_number_id      TEXT,           -- from Meta Developer Console
    wa_access_token         TEXT,           -- permanent system user token
    wa_verify_token         TEXT,           -- used to verify webhook ownership

    -- AI bot personality — this is what makes each client's bot unique.
    -- The system_prompt tells the AI who it is, what it sells, and how to behave.
    system_prompt           TEXT DEFAULT 'You are a helpful customer support agent. Be friendly and professional.',
    ai_model                TEXT DEFAULT 'gemini-2.0-flash',
    language                TEXT DEFAULT 'en',

    -- Billing and plan limits.
    -- The monthly_message_limit controls how many AI replies the client gets per month.
    plan                    TEXT DEFAULT 'starter' CHECK (plan IN ('starter', 'pro', 'enterprise')),
    monthly_message_limit   INTEGER DEFAULT 1000,
    messages_used           INTEGER DEFAULT 0,

    -- Stripe billing (fill in later when you add payments)
    stripe_customer_id      TEXT,
    stripe_subscription_id  TEXT,

    -- Soft delete: we set is_active = false instead of deleting the row.
    -- This preserves history and makes it easy to reactivate a client.
    is_active               BOOLEAN DEFAULT TRUE,

    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

-- ── Indexes ──────────────────────────────────────────────────
-- These make lookups fast. The two most common queries in your
-- webhook are: "find tenant by api_key" and "find tenant by phone number id".
-- Without indexes, Postgres scans every row — with indexes, it jumps directly.

CREATE INDEX IF NOT EXISTS idx_tenants_api_key
    ON tenants (api_key);

CREATE INDEX IF NOT EXISTS idx_tenants_wa_phone_number_id
    ON tenants (wa_phone_number_id);

CREATE INDEX IF NOT EXISTS idx_tenants_email
    ON tenants (email);

-- ── Auto-update updated_at ────────────────────────────────────
-- This trigger automatically sets updated_at = NOW() whenever
-- a row is modified, so you always know when a record last changed.

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER tenants_updated_at
    BEFORE UPDATE ON tenants
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ── Row Level Security ────────────────────────────────────────
-- Supabase enables RLS by default. We enable it here and add a
-- policy so your FastAPI backend (using the service_role key)
-- can read and write freely. If you later build a client-facing
-- dashboard using Supabase's client library, you would add
-- more restrictive policies per authenticated user.

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;

-- Service role (your FastAPI backend) bypasses RLS entirely,
-- so this policy only matters for direct client connections.
CREATE POLICY "Service role has full access to tenants"
    ON tenants
    FOR ALL
    USING (true);






-- ============================================================
-- PRODUCTS TABLE
-- Each client's product catalog lives here.
-- One tenant can have thousands of products.
-- The AI reads this table in real-time to answer stock questions.
-- ============================================================

CREATE TABLE IF NOT EXISTS products (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Foreign key ties every product to its owner (the tenant/client).
    -- ON DELETE CASCADE means if you delete a tenant, all their
    -- products are automatically deleted too — no orphaned rows.
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Core product identity
    name                TEXT NOT NULL,

    -- SKU = Stock Keeping Unit — the client's own internal product code.
    -- Useful when they want to update stock via their inventory system.
    sku                 TEXT,

    description         TEXT,
    category            TEXT,   -- e.g. "sneakers", "formal", "sandals"

    -- Pricing
    price               NUMERIC(10, 2),   -- e.g. 12500.00
    currency            TEXT DEFAULT 'LKR',

    -- Stock quantity is the live number — this is what the AI uses
    -- to tell customers "yes we have 15 in stock" or "sorry, sold out".
    stock_quantity      INTEGER DEFAULT 0,

    -- is_available is a quick flag. We set it automatically based on
    -- stock_quantity (see trigger below). The AI filters on this column.
    is_available        BOOLEAN DEFAULT TRUE,

    -- Variants stored as comma-separated strings for simplicity.
    -- e.g. sizes_available = "36,38,40,42,44"
    --      colors_available = "Black,White,Red"
    -- For a more advanced version you could normalise these into
    -- a separate product_variants table, but this works well for most clients.
    sizes_available     TEXT,
    colors_available    TEXT,

    -- Image URL for the dashboard product listing
    image_url           TEXT,

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── Indexes ───────────────────────────────────────────────────
-- The most common query is "get all available products for tenant X".
-- A composite index on (tenant_id, is_available) makes this very fast.

CREATE INDEX IF NOT EXISTS idx_products_tenant_id
    ON products (tenant_id);

CREATE INDEX IF NOT EXISTS idx_products_tenant_available
    ON products (tenant_id, is_available);

-- Full-text search index lets you search products by keyword efficiently.
-- This powers the search_products_by_keyword function for large catalogs.
CREATE INDEX IF NOT EXISTS idx_products_search
    ON products USING GIN (
        to_tsvector('english', name || ' ' || COALESCE(description, '') || ' ' || COALESCE(category, ''))
    );

-- Unique SKU per tenant — two different tenants CAN have the same SKU,
-- but within one tenant, SKUs must be unique.
CREATE UNIQUE INDEX IF NOT EXISTS idx_products_tenant_sku
    ON products (tenant_id, sku)
    WHERE sku IS NOT NULL;  -- partial index: only enforces when SKU is set

-- ── Auto-update triggers ──────────────────────────────────────

-- Reuse the same updated_at function we created for tenants.
CREATE OR REPLACE TRIGGER products_updated_at
    BEFORE UPDATE ON products
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- This trigger automatically sets is_available = false when stock
-- hits zero, and true when stock is replenished.
-- This way the AI always gets accurate availability without extra logic.
CREATE OR REPLACE FUNCTION sync_product_availability()
RETURNS TRIGGER AS $$
BEGIN
    -- If stock drops to 0 or below, mark unavailable automatically
    IF NEW.stock_quantity <= 0 THEN
        NEW.is_available = FALSE;
    ELSE
        NEW.is_available = TRUE;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER products_sync_availability
    BEFORE INSERT OR UPDATE OF stock_quantity ON products
    FOR EACH ROW
    EXECUTE FUNCTION sync_product_availability();

-- ── Row Level Security ────────────────────────────────────────

ALTER TABLE products ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role has full access to products"
    ON products
    FOR ALL
    USING (true);



-- ============================================================
-- CONVERSATIONS TABLE
-- Tracks each chat between a customer and a client's bot.
-- Redis holds the live message history for fast AI context,
-- but this table is the permanent record for analytics and
-- the client dashboard ("show me all chats from today").
-- ============================================================

CREATE TABLE IF NOT EXISTS conversations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- The end customer's WhatsApp number — this identifies the human
    -- who is chatting with the client's bot.
    customer_phone      TEXT NOT NULL,
    customer_name       TEXT,   -- pulled from WhatsApp contact profile

    -- When human agents take over, the AI stops replying.
    -- You set this to true when a client presses "Take Over" in the dashboard.
    is_human_takeover   BOOLEAN DEFAULT FALSE,

    -- Counts how many messages are in this conversation
    message_count       INTEGER DEFAULT 0,

    started_at          TIMESTAMPTZ DEFAULT NOW(),
    last_message_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id     UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,

    -- "user" = customer sent this, "assistant" = bot sent this
    role                TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content             TEXT NOT NULL,

    -- The WhatsApp message ID — used to prevent processing the same
    -- message twice (Meta sometimes delivers duplicates)
    wa_message_id       TEXT UNIQUE,

    tokens_used         INTEGER DEFAULT 0,   -- track AI cost per message
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_tenant_id
    ON conversations (tenant_id);

CREATE INDEX IF NOT EXISTS idx_conversations_phone
    ON conversations (tenant_id, customer_phone);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
    ON messages (conversation_id);

ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role has full access to conversations"
    ON conversations FOR ALL USING (true);

CREATE POLICY "Service role has full access to messages"
    ON messages FOR ALL USING (true);






-- ── Insert a test tenant ──────────────────────────────────────
INSERT INTO tenants (
    business_name,
    email,
    api_key,
    wa_verify_token,
    system_prompt,
    plan,
    monthly_message_limit
) VALUES (
    'ABC Shoes Colombo',
    'test@abcshoes.lk',
    'test-api-key-abc123',   -- in production, generate this with secrets.token_urlsafe(32)
    'test-verify-token-xyz',
    'You are a helpful support agent for ABC Shoes Colombo. We sell sneakers, formal shoes, and sandals. Sizes 36-46. Delivery 2-3 days island wide. Always be friendly and reply in the same language the customer uses.',
    'starter',
    1000
) RETURNING id, business_name, api_key;

-- ── Insert sample products under that tenant ──────────────────
-- First capture the tenant's id from the insert above,
-- then use it here. Replace the UUID below with your actual tenant id.

WITH tenant AS (
    SELECT id FROM tenants WHERE email = 'test@abcshoes.lk'
)
INSERT INTO products (tenant_id, name, sku, description, category, price, currency, stock_quantity, sizes_available, colors_available)
SELECT
    tenant.id,
    p.name, p.sku, p.description, p.category,
    p.price, p.currency, p.stock_quantity,
    p.sizes_available, p.colors_available
FROM tenant, (VALUES
    ('Nike Air Max 270',     'NK-AM270-BLK', 'Lightweight everyday runner',   'sneakers', 12500, 'LKR', 15, '36,38,40,42,44', 'Black,White'),
    ('Adidas Stan Smith',    'AD-SS-WHT',    'Classic court sneaker',          'sneakers',  9800, 'LKR',  8, '37,38,39,40,41,42', 'White,Green'),
    ('Oxford Formal Brogue', 'OX-BRG-BRN',  'Genuine leather dress shoe',     'formal',   18500, 'LKR',  0, '40,41,42,43,44', 'Brown,Black'),
    ('Havaianas Slim',       'HV-SLM-BLU',  'Everyday beach sandal',          'sandals',   3200, 'LKR', 30, '35,36,37,38,39,40', 'Blue,Pink,Yellow')
) AS p(name, sku, description, category, price, currency, stock_quantity, sizes_available, colors_available);

-- ── Verify the data looks correct ────────────────────────────
SELECT
    p.name,
    p.price,
    p.stock_quantity,
    p.is_available,   -- should be false for Oxford (stock=0), true for others
    p.sizes_available
FROM products p
JOIN tenants t ON t.id = p.tenant_id
WHERE t.email = 'test@abcshoes.lk'
ORDER BY p.category, p.name;





-- ============================================================
-- CONVERSATIONS TABLE
-- One row = one chat thread between a customer phone number
-- and one tenant's WhatsApp bot.
-- ============================================================

CREATE TABLE IF NOT EXISTS conversations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Cascade delete: when a tenant is removed, all their
    -- conversation data disappears automatically. No orphaned rows.
    tenant_id           UUID NOT NULL
                            REFERENCES tenants(id) ON DELETE CASCADE,

    -- The end customer's number, stored without the + symbol
    -- to match exactly how Meta sends it in webhook payloads.
    -- e.g. "94750688759" not "+94750688759"
    customer_phone      VARCHAR(20) NOT NULL,
    customer_name       VARCHAR(200),

    -- The AI pause button. When TRUE, process_and_reply returns
    -- immediately without calling Gemini.
    is_human_takeover   BOOLEAN NOT NULL DEFAULT FALSE,

    -- Cached message count avoids a slow COUNT(*) query every time
    -- the dashboard loads the conversation list.
    message_count       INTEGER NOT NULL DEFAULT 0,

    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_message_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- This is the most important index in your entire system.
-- Every single incoming message triggers a lookup like:
--   "find the conversation for tenant X and phone Y"
-- Without this index, Postgres scans every row in the table.
-- With it, the lookup is essentially instant even with millions of rows.
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_phone
    ON conversations (tenant_id, customer_phone);

-- Secondary index for the dashboard query:
-- "show me all conversations for tenant X, newest first"
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_recent
    ON conversations (tenant_id, last_message_at DESC);

-- ============================================================
-- MESSAGES TABLE
-- One row = one message bubble in a conversation.
-- Both customer messages (role='user') and AI replies
-- (role='assistant') are stored here.
-- ============================================================

CREATE TABLE IF NOT EXISTS messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Cascade delete: removing a conversation removes all its messages.
    conversation_id     UUID NOT NULL
                            REFERENCES conversations(id) ON DELETE CASCADE,

    -- Enforced at the database level: only these two values allowed.
    -- This prevents a bug in your application code from inserting
    -- a message with role='system' or role='bot' by accident.
    role                VARCHAR(20) NOT NULL
                            CHECK (role IN ('user', 'assistant')),

    -- TEXT has no length limit in PostgreSQL — safer than VARCHAR
    -- because long AI responses will never silently truncate.
    content             TEXT NOT NULL,

    message_type        VARCHAR(50) NOT NULL DEFAULT 'text',

    -- UNIQUE constraint is your database-level deduplication safety net.
    -- Even if your application code has a bug, the database will never
    -- store the same WhatsApp message twice.
    -- NULL values are excluded from uniqueness checks in PostgreSQL,
    -- so multiple rows with wa_message_id = NULL are perfectly fine
    -- (all your outgoing AI messages will have NULL here).
    wa_message_id       VARCHAR(500) UNIQUE,

    media_url           VARCHAR(1000),

    -- Tracks AI cost per message. Summing this column for a tenant
    -- gives you their total token consumption — essential for billing.
    tokens_used         INTEGER NOT NULL DEFAULT 0,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Primary lookup: "give me all messages in this conversation, oldest first"
-- This is what the dashboard chat view runs when a client opens a thread.
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
    ON messages (conversation_id, created_at ASC);

-- Secondary lookup: find a message by its WhatsApp ID quickly.
-- Used during deduplication checks and for marking messages as read.
CREATE INDEX IF NOT EXISTS idx_messages_wa_message_id
    ON messages (wa_message_id)
    WHERE wa_message_id IS NOT NULL;  -- partial index: skips NULL rows entirely,
                                      -- making the index smaller and faster

-- ============================================================
-- TRIGGER: Keep last_message_at current automatically
-- When a new message is inserted, we want the parent conversation's
-- last_message_at to update and message_count to increment.
-- Doing this in a trigger means you can never forget to do it
-- in your application code — the database handles it for you.
-- ============================================================

CREATE OR REPLACE FUNCTION update_conversation_on_new_message()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE conversations
    SET
        -- Set last_message_at to exactly when this message was created
        last_message_at = NEW.created_at,
        -- Increment the cached count by 1
        message_count   = message_count + 1
    WHERE id = NEW.conversation_id;

    -- RETURN NEW is required for AFTER INSERT triggers — it tells
    -- PostgreSQL to proceed normally with the original INSERT.
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER messages_update_conversation
    AFTER INSERT ON messages       -- fires AFTER the message row is committed
    FOR EACH ROW                   -- fires once per inserted row, not once per statement
    EXECUTE FUNCTION update_conversation_on_new_message();

-- ============================================================
-- ROW LEVEL SECURITY
-- Supabase enables RLS by default. Your FastAPI backend connects
-- using the service_role key which bypasses RLS, so the "full
-- access" policies below are what matter for your use case.
-- If you later build a client-facing dashboard using Supabase's
-- JavaScript client library directly (without going through FastAPI),
-- you would add more restrictive per-tenant policies here.
-- ============================================================

ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access to conversations"
    ON conversations FOR ALL USING (true);

CREATE POLICY "Service role full access to messages"
    ON messages FOR ALL USING (true);


-- ============================================================
-- VERIFY EVERYTHING WORKS
-- Run this after the above to confirm your setup is correct.
-- It inserts a test conversation and two messages, then reads
-- them back to make sure the trigger updated the count.
-- ============================================================

DO $$
DECLARE
    test_tenant_id   UUID;
    test_conv_id     UUID;
BEGIN
    -- Get the test tenant we created earlier
    SELECT id INTO test_tenant_id
    FROM tenants
    WHERE email = 'test@abcshoes.lk'
    LIMIT 1;

    -- Only run the test if the tenant exists
    IF test_tenant_id IS NOT NULL THEN

        -- Create a test conversation
        INSERT INTO conversations (tenant_id, customer_phone, customer_name)
        VALUES (test_tenant_id, '94750688759', 'Sahan Randika')
        RETURNING id INTO test_conv_id;

        -- Insert a customer message
        INSERT INTO messages (conversation_id, role, content, wa_message_id)
        VALUES (test_conv_id, 'user', 'Do you have size 42 in black?', 'wamid.test123');

        -- Insert an AI reply
        INSERT INTO messages (conversation_id, role, content)
        VALUES (test_conv_id, 'assistant', 'Yes! We have Nike Air Max 270 in size 42 in Black. Price is LKR 12,500. Would you like to order?');

        RAISE NOTICE 'Test data inserted successfully for conversation %', test_conv_id;
    ELSE
        RAISE NOTICE 'Skipping test — no test tenant found. Run the tenant seed script first.';
    END IF;
END $$;

-- Now verify the trigger worked correctly.
-- message_count should be 2, last_message_at should be recent.
SELECT
    c.customer_name,
    c.customer_phone,
    c.message_count,            -- should be 2 (trigger incremented it twice)
    c.last_message_at,
    c.is_human_takeover,
    COUNT(m.id) AS actual_message_count  -- should also be 2
FROM conversations c
LEFT JOIN messages m ON m.conversation_id = c.id
WHERE c.customer_phone = '94750688759'
GROUP BY c.id, c.customer_name, c.customer_phone,
         c.message_count, c.last_message_at, c.is_human_takeover;

-- Add password column to tenants so clients can log in directly
ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS password_hash TEXT;

-- Set a default password for your existing test tenant
-- Generate the hash in Python first:
--   from passlib.context import CryptContext
--   print(CryptContext(schemes=["bcrypt"]).hash("yourpassword"))
-- Then paste the result below:

UPDATE tenants
SET password_hash = '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj4J/HS.iZTi'
WHERE email = 'test@abcshoes.lk';


-- ============================================================
-- MIGRATION: Add flow_config column to tenants table
--
-- The flow_config stores the tenant's customized conversation
-- flow as a JSONB column. JSONB (not JSON) because:
-- 1. PostgreSQL can index into it for queries
-- 2. It validates JSON on insert — no malformed configs
-- 3. It's stored in binary format, faster to read
--
-- Run this once in Supabase SQL Editor.
-- ============================================================

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS flow_config JSONB DEFAULT NULL;

-- Add a comment so future developers know what this stores
COMMENT ON COLUMN tenants.flow_config IS
    'Tenant-customized conversation flow steps stored as JSON. '
    'NULL means use system defaults. '
    'Shape: { steps: [{ step_key, step_index, display_name, is_enabled, message, buttons, description }] }';


-- ── Verify ────────────────────────────────────────────────────
SELECT
    column_name,
    data_type,
    column_default,
    is_nullable
FROM information_schema.columns
WHERE table_name  = 'tenants'
  AND column_name = 'flow_config';


-- ── Example of what a saved flow_config looks like ───────────
-- You can manually test a tenant's config with:
/*
UPDATE tenants

SET flow_config = '{
  "steps": [
    {
      "step_index": 0,
      "step_key": "idle",
      "display_name": "Welcome",
      "is_enabled": true,
      "message": "Hello! Welcome to our store!",
      "buttons": [
        {"id": "flow_browse",  "title": "Browse"},
        {"id": "flow_support", "title": "Support"}
      ],
      "description": "Entry point"
    },
    {
      "step_index": 1,
      "step_key": "main_menu",
      "display_name": "Our Products",
      "is_enabled": true,
      "message": "what we have in stock. Tap to browse and select:",
      "buttons": [
        {"id": "flow_browse",  "title": "Browse"},
        {"id": "flow_support", "title": "Support"}
      ],
      "description": "Entry point"
    }
  ]
}'::jsonb
WHERE email = 'test@abcshoes.lk';
*/

-- SET flow_config = '{
--   "steps": [
--     {
--       "step_index": 0,
--       "step_key": "idle",
--       "display_name": "Welcome",
--       "is_enabled": true,
--       "message": "Hi {{customer_name}}! 👋 Welcome to *{{business_name}}*!\\n\\nHow can I help you today?",
--       "buttons": [
--         {"id": "flow_browse",  "title": "🛍️ Browse Products"},
--         {"id": "flow_order",   "title": "📦 My Orders"},
--         {"id": "flow_support", "title": "💬 Support"}
--       ],
--       "description": "Entry point"
--     },
--     {
--       "step_index": 1,
--       "step_key": "main_menu",
--       "display_name": "Main Menu",
--       "is_enabled": true,
--       "message": "Please choose an option below:",
--       "buttons": [
--         {"id": "flow_browse",  "title": "🛍️ Browse Products"},
--         {"id": "flow_order",   "title": "📦 My Orders"},
--         {"id": "flow_support", "title": "💬 Support"}
--       ],
--       "description": "Main options"
--     },
--     {
--       "step_index": 2,
--       "step_key": "browsing",
--       "display_name": "Browse Products",
--       "is_enabled": true,
--       "message": "Here are our available products 👇\\n\\nTap a product to see details and order.",
--       "buttons": [],
--       "action": {
--         "type": "product_list",
--         "function": "_send_product_list"
--       },
--       "description": "Shows product list grouped by category"
--     },
--     {
--       "step_index": 3,
--       "step_key": "product_detail",
--       "display_name": "Product Detail",
--       "is_enabled": true,
--       "message": "{{product_details}}",
--       "buttons": [
--         {"id": "flow_add_to_order", "title": "✅ Order This"},
--         {"id": "flow_back",         "title": "◀️ Back to List"},
--         {"id": "flow_main_menu",    "title": "🏠 Main Menu"}
--       ],
--       "description": "Shows selected product details"
--     },
--     {
--       "step_index": 4,
--       "step_key": "collect_quantity",
--       "display_name": "Collect Quantity",
--       "is_enabled": true,
--       "message": "Great choice! 🎉 You selected *{{product_name}}*.\\n\\nPlease enter the *quantity* you'd like to order:",
--       "buttons": [],
--       "description": "Ask quantity"
--     },
--     {
--       "step_index": 5,
--       "step_key": "collect_size",
--       "display_name": "Collect Size",
--       "is_enabled": true,
--       "message": "What *size* do you need? (e.g. 40, 42, 44)",
--       "buttons": [],
--       "description": "Ask size"
--     },
--     {
--       "step_index": 6,
--       "step_key": "collect_address",
--       "display_name": "Collect Address",
--       "is_enabled": true,
--       "message": "📍 What is your *delivery address*?",
--       "buttons": [],
--       "description": "Ask delivery address"
--     },
--     {
--       "step_index": 7,
--       "step_key": "confirm_order",
--       "display_name": "Confirm Order",
--       "is_enabled": true,
--       "message": "📋 *Order Summary*\\n\\nProduct : {{product_name}}\\nSize    : {{size}}\\nQty     : {{quantity}}\\nAddress : {{address}}\\nTotal   : {{currency}} {{total}}\\n\\nDelivery in 2-3 business days. 🚚",
--       "buttons": [
--         {"id": "flow_confirm", "title": "✅ Confirm Order"},
--         {"id": "flow_cancel",  "title": "❌ Cancel"}
--       ],
--       "description": "Final confirmation"
--     },
--     {
--       "step_index": 8,
--       "step_key": "support",
--       "display_name": "Support",
--       "is_enabled": true,
--       "message": "💬 *Support*\\n\\nTell me what you need help with and I'll assist you right away.",
--       "buttons": [],
--       "description": "Customer support"
--     }
--   ]
-- }'::jsonb
-- WHERE email = 'test@abcshoes.lk';