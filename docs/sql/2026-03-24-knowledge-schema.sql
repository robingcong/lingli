CREATE TABLE IF NOT EXISTS `knowledge_document` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `source_path` varchar(500) NOT NULL,
  `title` varchar(255) NOT NULL,
  `doc_type` varchar(32) NOT NULL DEFAULT '',
  `content` longtext NOT NULL,
  `content_hash` varchar(64) NOT NULL,
  `file_mtime` double NOT NULL DEFAULT 0,
  `chunk_count` int NOT NULL DEFAULT 0,
  `status` varchar(32) NOT NULL DEFAULT 'indexed',
  `last_indexed_at` datetime NULL DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_knowledge_document_source_path` (`source_path`),
  KEY `idx_knowledge_document_hash` (`content_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `knowledge_chunk` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `document_id` bigint NOT NULL,
  `chunk_id` varchar(128) NOT NULL,
  `chunk_index` int NOT NULL DEFAULT 0,
  `content` longtext NOT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_knowledge_chunk_chunk_id` (`chunk_id`),
  KEY `idx_knowledge_chunk_document_id` (`document_id`),
  CONSTRAINT `fk_knowledge_chunk_document`
    FOREIGN KEY (`document_id`) REFERENCES `knowledge_document` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
