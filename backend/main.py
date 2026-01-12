import os
from fastapi import FastAPI, Request
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Configuration Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") 
db: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

# --- ROUTE 1 : INITIALISATION DE L'APPEL ---
@app.post("/call/init")
async def init_call(request: Request):
    payload = await request.json()
    print("📥 Payload Init reçu")

    # Identification du numéro (Gestion Web + Mobile)
    called_number = payload.get('message', {}).get('phone_number', {}).get('number')
    if not called_number:
        called_number = '+12406509923' # On simule Luigi pour les tests

    # Identifier le restaurant
    response = db.table('restaurants').select("*").eq('twilio_phone_number', called_number).execute()
    if not response.data:
        return {"assistant": {"firstMessage": "Restaurant non trouvé."}}
    
    resto = response.data[0]

    # --- NOUVEAU : On ne met plus les prix en dur, on donne les OUTILS ---
    system_instruction = f"""
    Tu es l'assistant vocal de {resto['name']}.
    Tu as accès à 2 outils CRUCIAUX :
    1. 'get_menu' : Utilise-le au début ou si on te demande un prix/plat.
    2. 'book_table' : Utilise-le pour enregistrer une réservation.

    Règles :
    - Ne devine JAMAIS un prix. Si tu ne le connais pas, appelle 'get_menu'.
    - Si le client demande un plat avec un nom proche, l'outil te donnera la liste exacte pour corriger.
    - Demande toujours : Nom, Nombre de personnes, et Heure.
    """

    return {
        "assistant": {
            "firstMessage": f"Bienvenue chez {resto['name']} ! Comment puis-je vous aider ?",
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini", # On passe en mini pour réduire la latence < 1000ms
                "systemPrompt": system_instruction,
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_menu",
                            "description": "Récupère la liste complète des plats et prix du restaurant.",
                            "parameters": {"type": "object", "properties": {}}
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "book_table",
                            "description": "Enregistrer une réservation dans la base de données.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "customer_name": {"type": "string"},
                                    "party_size": {"type": "integer"},
                                    "reservation_datetime": {"type": "string", "description": "Format ISO ou texte clair"}
                                },
                                "required": ["customer_name", "party_size", "reservation_datetime"]
                            }
                        }
                    }
                ]
            }
        }
    }

# --- ROUTE 2 : OUTIL CONSULTATION MENU (Intelligent) ---
@app.post("/tools/get_menu")
async def get_menu(request: Request):
    payload = await request.json()
    # On récupère le resto_id via le numéro simulé ou réel
    called_number = payload.get('message', {}).get('call', {}).get('phone_number', {}).get('number') or '+12406509923'
    
    resto_resp = db.table('restaurants').select("id").eq('twilio_phone_number', called_number).execute()
    resto_id = resto_resp.data[0]['id']

    # On récupère TOUT le menu_items
    menu_resp = db.table('menu_items').select("name, price").eq('restaurant_id', resto_id).eq('is_available', True).execute()
    
    return {"results": menu_resp.data}

# --- ROUTE 3 : L'OUTIL DE RÉSERVATION ---
@app.post("/tools/book_table")
async def book_table(request: Request):
    payload = await request.json()
    args = payload.get('message', {}).get('toolCalls', [{}])[0].get('function', {}).get('arguments', {})
    
    called_number = payload.get('message', {}).get('call', {}).get('phone_number', {}).get('number') or '+12406509923'
    resto_resp = db.table('restaurants').select("id").eq('twilio_phone_number', called_number).execute()
    
    try:
        db.table('reservations').insert({
            "restaurant_id": resto_resp.data[0]['id'],
            "customer_name": args.get('customer_name'),
            "party_size": args.get('party_size'),
            "reservation_time": args.get('reservation_datetime'),
            "status": "confirmed"
        }).execute()
        return {"result": "La réservation est bien enregistrée dans le système."}
    except Exception as e:
        return {"result": f"Erreur lors de l'enregistrement : {str(e)}"}