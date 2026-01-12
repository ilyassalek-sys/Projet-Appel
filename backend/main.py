import os
from fastapi import FastAPI, HTTPException, Request
from supabase import create_client, Client
from pydantic import BaseModel
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
    print("📥 Payload Init reçu:", payload) # Pour tes logs Railway

    # 1. Récupération du numéro appelé
    try:
        # Chemin standard Vapi
        called_number = payload.get('message', {}).get('phone_number', {}).get('number')
    except:
        called_number = None

    # --- 🚨 DÉBUT ASTUCE TEST WEB ---
    # Si on ne trouve pas de numéro (test depuis le navigateur), on force le numéro US
    if not called_number:
        print("⚠️ Appel Web détecté : On simule le numéro de Luigi !")
        called_number = '+12406509923' 
    # --- 🚨 FIN ASTUCE ---

    # 2. Identifier le restaurant dans Supabase
    response = db.table('restaurants').select("*").eq('twilio_phone_number', called_number).execute()
    
    if not response.data:
        print(f"❌ Erreur : Aucun restaurant trouvé pour le numéro {called_number}")
        return {
            "assistant": {
                "firstMessage": "Désolé, je ne trouve pas le restaurant associé à ce numéro.",
                "model": {"provider": "openai", "model": "gpt-4o", "messages": []}
            }
        }
    
    resto = response.data[0]
    print(f"✅ Restaurant trouvé : {resto['name']}")

    # 3. Récupérer le menu ACTIF
    menu_resp = db.table('menu_items').select("*").eq('restaurant_id', resto['id']).eq('is_available', True).execute()
    menu_text = "\n".join([f"- {m['name']} ({m['price']}€)" for m in menu_resp.data])

    # 4. Construire le Prompt Système
    system_instruction = f"""
    Tu es l'assistant vocal du restaurant {resto['name']}.
    Ton rôle est de prendre des réservations et répondre aux questions sur le menu.
    
    MENU ACTUEL DU JOUR :
    {menu_text}
    IMPORTANT : Si un client demande un plat qui n'est pas dans cette liste, dis poliment qu'il est en rupture.
    
    Règles :
    - Sois chaleureux et bref.
    - Demande toujours : Nom, Nombre de personnes, et Heure souhaitée.
    - Une fois les infos obtenues, utilise l'outil 'book_table'.
    """

    # 5. Retourner la config à Vapi
    return {
        "assistant": {
            "model": {
                "provider": "openai",
                "model": "gpt-4o",
                "systemPrompt": system_instruction,
                "functions": [
                    {
                        "name": "book_table",
                        "description": "Enregistrer une réservation.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "customer_name": {"type": "string"},
                                "party_size": {"type": "integer"},
                                "reservation_datetime": {"type": "string"}
                            },
                            "required": ["customer_name", "party_size", "reservation_datetime"]
                        }
                    }
                ]
            }
        }
    }

# --- ROUTE 2 : L'OUTIL DE RÉSERVATION ---
@app.post("/tools/book_table")
async def book_table(request: Request):
    payload = await request.json()
    print("📥 Payload Outil reçu:", payload)

    # Extraction des arguments de GPT
    args = payload.get('message', {}).get('functionCall', {}).get('parameters', {})
    
    # On doit retrouver le restaurant.
    # Dans un outil, Vapi renvoie aussi le contexte de l'appel.
    call_data = payload.get('message', {}).get('call', {})
    called_number = call_data.get('phone_number', {}).get('number')

    # --- 🚨 DÉBUT ASTUCE TEST WEB (Aussi pour l'outil) ---
    if not called_number:
        called_number = '+12406509923'
    # --- 🚨 FIN ASTUCE ---
    
    # Recherche ID Resto
    resto_resp = db.table('restaurants').select("id").eq('twilio_phone_number', called_number).execute()
    if not resto_resp.data:
        return {"result": "Erreur technique: Restaurant introuvable."}
    
    restaurant_id = resto_resp.data[0]['id']

    # Insertion dans Supabase
    try:
        db.table('reservations').insert({
            "restaurant_id": restaurant_id,
            "customer_name": args.get('customer_name'),
            "party_size": args.get('party_size'),
            "reservation_time": args.get('reservation_datetime'), 
            "customer_phone": call_data.get('customer', {}).get('number', 'WebUser'), # Numéro client ou "WebUser"
            "status": "confirmed"
        }).execute()
        
        return {"result": "Réservation confirmée avec succès !"}
    except Exception as e:
        print(f"❌ Erreur BDD : {str(e)}")
        return {"result": "J'ai eu un problème pour noter la réservation."}