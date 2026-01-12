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

    called_number = payload.get('message', {}).get('phone_number', {}).get('number')
    if not called_number:
        called_number = '+12406509923' # Numéro simulé

    response = db.table('restaurants').select("*").eq('twilio_phone_number', called_number).execute()
    if not response.data:
        return {"assistant": {"firstMessage": "Désolé, je ne trouve pas ce restaurant."}}
    
    resto = response.data[0]

    system_instruction = f"""
    Tu es l'assistant vocal de {resto['name']}.
    Tu dois utiliser l'outil 'get_menu' pour les prix et 'book_table' pour réserver.

    Instructions Réservation :
    1. Demande le nom, le nombre de personnes et l'heure précise.
    2. Ne confirme la réservation QUE lorsque tu as ces 3 infos.
    3. Une fois les infos reçues, appelle 'book_table' IMMÉDIATEMENT.
    """

    return {
        "assistant": {
            "firstMessage": f"Bienvenue chez {resto['name']} ! Que puis-je faire pour vous ?",
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "systemPrompt": system_instruction,
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_menu",
                            "description": "Liste des plats et prix.",
                            "parameters": {"type": "object", "properties": {}}
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "book_table",
                            "description": "Enregistrer la réservation dans Supabase.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "Nom du client"},
                                    "size": {"type": "integer", "description": "Nombre de personnes"},
                                    "time": {"type": "string", "description": "Heure et date"}
                                },
                                "required": ["name", "size", "time"]
                            }
                        }
                    }
                ]
            }
        }
    }

# --- ROUTE 2 : OUTIL MENU ---
@app.post("/tools/get_menu")
async def get_menu(request: Request):
    payload = await request.json()
    called_number = payload.get('message', {}).get('call', {}).get('phone_number', {}).get('number') or '+12406509923'
    
    resto_resp = db.table('restaurants').select("id").eq('twilio_phone_number', called_number).execute()
    resto_id = resto_resp.data[0]['id']

    menu_resp = db.table('menu_items').select("name, price").eq('restaurant_id', resto_id).eq('is_available', True).execute()
    return {"results": menu_resp.data}

# --- ROUTE 3 : OUTIL RÉSERVATION (Fix pour les colonnes NULL) ---
@app.post("/tools/book_table")
async def book_table(request: Request):
    payload = await request.json()
    
    # Correction : On va chercher les arguments au bon endroit dans le payload Vapi
    tool_call = payload.get('message', {}).get('toolCalls', [{}])[0]
    args = tool_call.get('function', {}).get('arguments', {})
    
    # Récupération du numéro de téléphone du client
    customer_phone = payload.get('message', {}).get('call', {}).get('customer', {}).get('number') or "Web User"
    
    # Identification du restaurant
    called_number = payload.get('message', {}).get('call', {}).get('phone_number', {}).get('number') or '+12406509923'
    resto_resp = db.table('restaurants').select("id").eq('twilio_phone_number', called_number).execute()
    restaurant_id = resto_resp.data[0]['id']
    
    try:
        # Mapping précis avec tes colonnes Supabase
        db.table('reservations').insert({
            "restaurant_id": restaurant_id,
            "customer_phone": customer_phone,       # Colonne customer_phone
            "customer_name": args.get('name'),      # Colonne customer_name
            "party_size": args.get('size'),         # Colonne party_size
            "reservation_time": args.get('time'),   # Colonne reservation_time
            "status": "confirmed"                   # Colonne status
        }).execute()
        
        return {"result": "Réservation confirmée, j'ai tout noté !"}
    except Exception as e:
        print(f"❌ Erreur d'insertion : {str(e)}")
        return {"result": "Désolé, j'ai une erreur technique pour noter cela."}