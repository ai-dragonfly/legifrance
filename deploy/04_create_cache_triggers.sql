-- ================================================================
-- Phase 4c : Triggers invalidation cache automatique
-- ================================================================
-- 
-- Objectif : Détecter modifications sections/articles et invalider 
--            automatiquement le cache du code parent
-- 
-- Déploiement : psql -U legifrance_app -d legifrance -f 04_create_cache_triggers.sql
-- ================================================================

-- 1. Fonction trigger : Invalidation cache quand section modifiée
CREATE OR REPLACE FUNCTION invalidate_code_tree()
RETURNS TRIGGER AS $$
DECLARE
    parent_code TEXT;
BEGIN
    -- Récupérer code parent depuis section
    parent_code := NEW.meta->>'parent';
    
    -- Si parent est un code (LEGITEXT ou JORFTEXT)
    IF parent_code LIKE 'LEGITEXT%' OR parent_code LIKE 'JORFTEXT%' THEN
        -- Invalider cache en reculant updated_at de 25h
        -- (le script regenerate_stale_caches détectera updated_at < NOW() - 24h)
        UPDATE code_trees 
        SET updated_at = NOW() - INTERVAL '25 hours'
        WHERE code_id = parent_code;
        
        -- Log invalidation pour monitoring
        INSERT INTO cache_invalidations (code_id, reason, triggered_at, document_id)
        VALUES (parent_code, 'section_modified', NOW(), NEW.meta->>'id');
        
        RAISE NOTICE 'Cache invalidé pour code %', parent_code;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 2. Trigger sur INSERT/UPDATE sections
DROP TRIGGER IF EXISTS trigger_invalidate_cache_section ON documents;

CREATE TRIGGER trigger_invalidate_cache_section
AFTER INSERT OR UPDATE ON documents
FOR EACH ROW
WHEN (NEW.doctype = 'section' AND NEW.meta->>'parent' IS NOT NULL)
EXECUTE FUNCTION invalidate_code_tree();

-- 3. Fonction trigger : Invalidation cache quand article modifié
-- (Articles modifiés nécessitent aussi régénération arbre si include_articles=True)
CREATE OR REPLACE FUNCTION invalidate_code_tree_article()
RETURNS TRIGGER AS $$
DECLARE
    parent_section TEXT;
    parent_code TEXT;
BEGIN
    -- Articles ont meta->>'parent' pointant vers section ou code
    parent_section := NEW.meta->>'parent';
    
    -- Si parent est une section, trouver le code parent
    IF parent_section LIKE 'LEGISCTA%' THEN
        SELECT meta->>'parent' INTO parent_code
        FROM documents
        WHERE source = 'LEGI'
          AND doctype = 'section'
          AND meta->>'id' = parent_section
        LIMIT 1;
    ELSIF parent_section LIKE 'LEGITEXT%' OR parent_section LIKE 'JORFTEXT%' THEN
        parent_code := parent_section;
    END IF;
    
    -- Invalider cache code
    IF parent_code IS NOT NULL THEN
        UPDATE code_trees 
        SET updated_at = NOW() - INTERVAL '25 hours'
        WHERE code_id = parent_code;
        
        INSERT INTO cache_invalidations (code_id, reason, triggered_at, document_id)
        VALUES (parent_code, 'article_modified', NOW(), NEW.meta->>'id');
        
        RAISE NOTICE 'Cache invalidé pour code % (article modifié)', parent_code;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 4. Trigger sur INSERT/UPDATE articles
DROP TRIGGER IF EXISTS trigger_invalidate_cache_article ON documents;

CREATE TRIGGER trigger_invalidate_cache_article
AFTER INSERT OR UPDATE ON documents
FOR EACH ROW
WHEN (NEW.doctype = 'article' AND NEW.meta->>'parent' IS NOT NULL)
EXECUTE FUNCTION invalidate_code_tree_article();

-- 5. Vérification triggers créés
SELECT 
    tgname as trigger_name,
    tgtype as trigger_type,
    tgenabled as enabled
FROM pg_trigger
WHERE tgname LIKE 'trigger_invalidate_cache%'
ORDER BY tgname;

-- 6. Statistiques invalidations existantes
SELECT 
    reason,
    COUNT(*) as count,
    MIN(triggered_at) as first_invalidation,
    MAX(triggered_at) as last_invalidation
FROM cache_invalidations
GROUP BY reason
ORDER BY count DESC;

-- ================================================================
-- ✅ Triggers créés avec succès !
-- ================================================================
