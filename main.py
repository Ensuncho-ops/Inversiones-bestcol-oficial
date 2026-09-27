from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo import MongoClient
from typing import List
import time

app = FastAPI()

# Permisos CORS para conectar con tu index.html
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================
# CONEXIÓN A MONGODB (Aquí pondremos el link de la nube después)
# Por ahora usa una conexión local si tienes MongoDB instalado, 
# o puedes crear tu cluster en MongoDB Atlas y pegar el enlace aquí.
# ==============================================================
MONGO_URI = "mongodb+srv://admin:Felipe12345@inversionesbestcol.fix2aui.mongodb.net/?appName=inversionesbestcol"
client = MongoClient(MONGO_URI)
db = client["wms_bestcol"]
inventario_col = db["inventario"]

# --- MODELOS DE DATOS ---
class LoginData(BaseModel):
    usuario: str
    password: str

class ProductoNuevo(BaseModel):
    sku: str
    nombre_oficial: str
    categoria: str
    cantidad: int

class ProductoActualizar(BaseModel):
    sku: str
    cambio: int

class ProductoEliminar(BaseModel):
    sku: str

class LoteProducto(BaseModel):
    nombre_oficial: str
    categoria: str
    cantidad: int

class LoteEntrada(BaseModel):
    productos: List[LoteProducto]

class EscaneoSalida(BaseModel):
    codigo_guia: str
    nombre_producto: str
    cantidad_requerida: int
    usuario: str

# --- ENDPOINTS ---

@app.post("/api/login")
def login(data: LoginData):
    # Lógica de prueba simple
    if data.usuario == "admin" and data.password == "admin":
        return {"ok": True, "token": "token-wms-bestcol"}
    return {"ok": False}

@app.get("/api/inventario")
def get_inventario():
    # Obtener todos los productos (excluyendo el ObjectId de Mongo)
    items = list(inventario_col.find({}, {"_id": 0}))
    return {"ok": True, "inventario": items}

@app.post("/api/inventario/crear")
def crear_producto(data: ProductoNuevo):
    if inventario_col.find_one({"sku": data.sku}):
        raise HTTPException(status_code=400, detail="El SKU ya existe")
    
    inventario_col.insert_one(data.dict())
    return {"ok": True, "mensaje": "Producto creado con éxito"}

@app.post("/api/inventario/actualizar")
def actualizar_stock(data: ProductoActualizar):
    res = inventario_col.update_one({"sku": data.sku}, {"$inc": {"cantidad": data.cambio}})
    if res.modified_count == 0:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return {"ok": True}

@app.post("/api/inventario/eliminar")
def eliminar_producto(data: ProductoEliminar):
    inventario_col.delete_one({"sku": data.sku})
    return {"ok": True}

@app.post("/api/inventario/entrada_lote")
def entrada_lote(data: LoteEntrada):
    for p in data.productos:
        # Busca si ya existe usando búsqueda ignorando mayúsculas/minúsculas
        existente = inventario_col.find_one({"nombre_oficial": {"$regex": f"^{p.nombre_oficial}$", "$options": "i"}})
        if existente:
            inventario_col.update_one({"_id": existente["_id"]}, {"$inc": {"cantidad": p.cantidad}})
        else:
            # Si es nuevo por completo, se auto-genera un SKU temporal
            nuevo_sku = f"SKU-{int(time.time())}"
            inventario_col.insert_one({
                "sku": nuevo_sku,
                "nombre_oficial": p.nombre_oficial,
                "categoria": p.categoria,
                "cantidad": p.cantidad
            })
            time.sleep(1) # Para evitar SKUs duplicados en bucle rápido
            
    return {"ok": True, "mensaje": f"Se ingresaron {len(data.productos)} registros"}

@app.post("/api/escanear_salida")
def escanear_salida(data: EscaneoSalida):
    # 1. Limpieza Inteligente del nombre que viene del PDF
    nombre_sucio = data.nombre_producto
    nombre_limpio = nombre_sucio.split("Notas:")[0].split("Nro:")[0].split(" X ")[0].strip()
    
    # Extraemos solo las primeras palabras clave por si está escrito distinto
    palabras = nombre_limpio.split()[:3] 
    busqueda_flexible = ".*".join(palabras) # Ej: "Abrigo.*Virgen.*Guadalupe"

    # 2. Buscar en MongoDB ($regex = búsqueda parcial, $options: "i" = ignora mayúsculas)
    producto = inventario_col.find_one({"nombre_oficial": {"$regex": nombre_limpio, "$options": "i"}})
    
    if not producto: # Si no lo encuentra exacto, busca por palabras clave
        producto = inventario_col.find_one({"nombre_oficial": {"$regex": busqueda_flexible, "$options": "i"}})
        
    if not producto:
        raise HTTPException(status_code=400, detail=f"No se halló en la nube: '{nombre_limpio}'")
        
    # 3. Descontar Stock
    nuevo_stock = producto["cantidad"] - data.cantidad_requerida
    inventario_col.update_one({"_id": producto["_id"]}, {"$set": {"cantidad": nuevo_stock}})
    
    return {
        "ok": True, 
        "mensaje": f"Se descontó 1 de {producto['nombre_oficial']} (Quedan: {nuevo_stock})"
    }
@app.get("/api/guias")
def obtener_guias():
    try:
        # Busca el documento de guías en Mongo
        doc = db.guias_sync.find_one({"_id": "estado_global"})
        return {"ok": True, "guias": doc.get("data", {}) if doc else {}}
    except Exception as e:
        return {"ok": False, "guias": {}}

@app.post("/api/guias")
def guardar_guias(guias_data: dict):
    try:
        # Guarda y sobreescribe las guías en Mongo
        db.guias_sync.update_one(
            {"_id": "estado_global"},
            {"$set": {"data": guias_data}},
            upsert=True
        )
        return {"ok": True}
    except Exception as e:
        return {"ok": False}
