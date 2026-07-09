-- Migration 005: Member Review Status Update
-- Standardizes members.status to include 'verified' and 'rejected',
-- and adds audit columns reviewed_by and reviewed_at.

-- 1. Drop existing check constraint on members.status if exists
ALTER TABLE public.members DROP CONSTRAINT IF EXISTS members_status_check;

-- 2. Add check constraint allowing active, need_review, verified, rejected, excluded
ALTER TABLE public.members ADD CONSTRAINT members_status_check 
  CHECK (status IN ('active', 'need_review', 'verified', 'rejected', 'excluded'));

-- 3. Add audit fields to the members table
ALTER TABLE public.members ADD COLUMN IF NOT EXISTS reviewed_by UUID REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE public.members ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP WITH TIME ZONE;
