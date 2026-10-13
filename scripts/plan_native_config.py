"""Common native settings for the newly frozen Luna full run."""
from scripts.run_plan_health import configurations
from scripts.local_embeddings import MODEL


def full_configurations(bin_dir, base, embedding_url):
    rows=configurations(bin_dir,base)
    for row in rows:
        row['timeout']=180
        if row['kind']=='openclaw':
            row['native_config']['memory']={'search':{'provider':'openai-compatible','model':MODEL,
                'remote':{'baseUrl':embedding_url,'apiKey':'local-embedding-no-external-credential'}}}
    return rows
