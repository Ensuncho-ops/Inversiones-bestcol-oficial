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
 
    # 1. Limpieza Inteligente y extracción de cantidad
    nombre_sucio = data.nombre_producto
    
    import re
    # Buscamos el multiplicador (ej. "X 2", "x3") en todo el texto original
    match_cant = re.search(r'[xX]\s*(\d+)', nombre_sucio)
    cantidad_a_descontar = int(match_cant.group(1)) if match_cant else 1

    # Limpiamos el nombre para buscar el producto en la base de datos
    nombre_limpio = nombre_sucio.split("Notas:")[0].split("Nro:")[0].split("ID")[0].split("X")[0].strip()
    
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
    nuevo_stock = producto["cantidad"] - cantidad_a_descontar
    inventario_col.update_one({"_id": producto["_id"]}, {"$set": {"cantidad": nuevo_stock}})
    
    return {
        "ok": True, 
        "mensaje": f"Se descontó {cantidad_a_descontar} de {producto['nombre_oficial']} (Quedan: {nuevo_stock})"
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
        
@app.get("/api/importar-masivo")
def importar_masivo():
    productos_iniciales = [
        # --- ABRIGOS ---
        {"sku": "ABR-GUAD-01", "nombre_oficial": "Abrigo Virgen Guadalupe", "categoria": "Abrigos", "cantidad": 15},
        {"sku": "ABR-VCAR-NUE", "nombre_oficial": "Abrigo Virgen del Carmen Nuevo", "categoria": "Abrigos", "cantidad": 38},
        {"sku": "ABR-ROSA-01", "nombre_oficial": "Abrigo Rosa Mistica", "categoria": "Abrigos", "cantidad": 1},
        {"sku": "ABR-BRAH-UNI", "nombre_oficial": "Abrigo Brahmán Único", "categoria": "Abrigos", "cantidad": 8},
        {"sku": "ABR-TEJ-BLA", "nombre_oficial": "Abrigo Tejido - Blanco", "categoria": "Abrigos", "cantidad": 6},
        {"sku": "ABR-TEJ-NEG", "nombre_oficial": "Abrigo Tejido - Negro", "categoria": "Abrigos", "cantidad": 16},
        {"sku": "ABR-TEJ-ROS", "nombre_oficial": "Abrigo Tejido - Rosado", "categoria": "Abrigos", "cantidad": 23},
        {"sku": "ABR-DIV-NIN", "nombre_oficial": "Abrigo Divino Niño", "categoria": "Abrigos", "cantidad": 80},
        {"sku": "ABR-PAD-POT", "nombre_oficial": "Dia del padre potro", "categoria": "Abrigos", "cantidad": 23},
        {"sku": "ABR-SAN-RAF", "nombre_oficial": "Manta San Rafael", "categoria": "Abrigos", "cantidad": 23},
        {"sku": "ABR-SAN-JOS", "nombre_oficial": "Abrigo San Jose", "categoria": "Abrigos", "cantidad": 2},
        {"sku": "ABR-MILAGRO", "nombre_oficial": "Abrigo Virgen de la Milagrosa", "categoria": "Abrigos", "cantidad": 81},
        {"sku": "ABR-ENC-BLA", "nombre_oficial": "Abrigo Encanto - Blanco", "categoria": "Abrigos", "cantidad": 1},
        {"sku": "ABR-ENC-ROS", "nombre_oficial": "Abrigo Encanto - Rosado", "categoria": "Abrigos", "cantidad": 1},
        {"sku": "CUE-CAM-CAF", "nombre_oficial": "Cuello Camisero - Café", "categoria": "Insumos", "cantidad": 1},
        {"sku": "CUE-CAM-BEI", "nombre_oficial": "Cuello Camisero - Beige", "categoria": "Insumos", "cantidad": 1},

        # --- MANTOS ---
        {"sku": "ABR-MANTO-JES", "nombre_oficial": "Manto sagrado corazón de Jesús", "categoria": "Mantos", "cantidad": 1},
        {"sku": "MNT-MTO-CHAL", "nombre_oficial": "Manto Tipo Chal", "categoria": "Mantos", "cantidad": 1},
        {"sku": "MNT-EDEN", "nombre_oficial": "Manto Edn", "categoria": "Mantos", "cantidad": 5},
        {"sku": "MNT-MAD-CEL", "nombre_oficial": "Manto Madre Celestial", "categoria": "Mantos", "cantidad": 2},
        {"sku": "MNT-GUAD-BOR", "nombre_oficial": "Manto Guadalupe Bordado", "categoria": "Mantos", "cantidad": 4},

        # --- BORREGOS ---
        {"sku": "BOR-VCAR", "nombre_oficial": "Borrego Virgen del Carmen", "categoria": "Borregos", "cantidad": 12},
        {"sku": "BOR-VFAT", "nombre_oficial": "Borrego Virgen de Fatima", "categoria": "Borregos", "cantidad": 20},
        {"sku": "BOR-SMIG", "nombre_oficial": "Borrego San Miguel Arcangel", "categoria": "Borregos", "cantidad": 3},

        # --- POLAR ---
        {"sku": "POL-DAM-VIN", "nombre_oficial": "Polar para Dama - Vinotinto", "categoria": "Polar", "cantidad": 12},
        {"sku": "POL-DAM-MAR", "nombre_oficial": "Polar para Dama - Marfil", "categoria": "Polar", "cantidad": 10},
        {"sku": "POL-DAM-CAF", "nombre_oficial": "Polar para Dama - Café", "categoria": "Polar", "cantidad": 5},

        # --- BRAHAM ---
        {"sku": "BRAH-RAI-BLA", "nombre_oficial": "Braham Bordado - Blanco", "categoria": "Braham", "cantidad": 6},
        {"sku": "BRAH-RAI-NEG", "nombre_oficial": "Braham Bordado - Negro", "categoria": "Braham", "cantidad": 10},
        {"sku": "BRAH-RAI-CAF", "nombre_oficial": "Braham Bordado - Café", "categoria": "Braham", "cantidad": 1},

        # --- PVC (Incluyendo Rollos PVC) ---
        {"sku": "PVC-1M", "nombre_oficial": "PVC 1 M", "categoria": "PVC", "cantidad": 112},
        {"sku": "PVC-1.5M", "nombre_oficial": "PVC 1.5 M", "categoria": "PVC", "cantidad": 0},
        {"sku": "PVC-2M", "nombre_oficial": "PVC 2 M", "categoria": "PVC", "cantidad": 2},
        {"sku": "PVC-ROL-30M", "nombre_oficial": "Rollos PVC 30 M", "categoria": "PVC", "cantidad": 0},
        {"sku": "PVC-ROL-40M", "nombre_oficial": "Rollos PVC 40 M", "categoria": "PVC", "cantidad": 12},

        # --- MANTELES (Incluyendo Rollos Manteles) ---
        {"sku": "MAN6-ORO", "nombre_oficial": "Manteles 2,2 - 6 Puestos - Oro", "categoria": "Manteles", "cantidad": 7},
        {"sku": "MAN6-ENC", "nombre_oficial": "Manteles 2,2 - 6 Puestos - Encanto", "categoria": "Manteles", "cantidad": 3},
        {"sku": "MAN6-IMP", "nombre_oficial": "Manteles 2,2 - 6 Puestos - Imperial", "categoria": "Manteles", "cantidad": 3},
        {"sku": "MAN6-PLA", "nombre_oficial": "Manteles 2,2 - 6 Puestos - Plateado", "categoria": "Manteles", "cantidad": 4},
        {"sku": "MAN6-FLO", "nombre_oficial": "Manteles 2,2 - 6 Puestos - Florenza", "categoria": "Manteles", "cantidad": 6},
        {"sku": "MAN4-ORO", "nombre_oficial": "Manteles 1,8 - 4 Puestos - Oro", "categoria": "Manteles", "cantidad": 16},
        {"sku": "MAN4-ROS", "nombre_oficial": "Manteles 1,8 - 4 Puestos - Rosa", "categoria": "Manteles", "cantidad": 3},
        {"sku": "MAN4-ENC", "nombre_oficial": "Manteles 1,8 - 4 Puestos - Encanto", "categoria": "Manteles", "cantidad": 7},
        {"sku": "MAN4-PLA", "nombre_oficial": "Manteles 1,8 - 4 Puestos - Plateado", "categoria": "Manteles", "cantidad": 4},
        {"sku": "MAN4-FLO", "nombre_oficial": "Manteles 1,8 - 4 Puestos - Florenza", "categoria": "Manteles", "cantidad": 2},
        {"sku": "MAN-ROL-ORO", "nombre_oficial": "Rollos Manteles Oro", "categoria": "Manteles", "cantidad": 2},
        {"sku": "MAN-ROL-ROS", "nombre_oficial": "Rollos Manteles Rosa", "categoria": "Manteles", "cantidad": 3},
        {"sku": "MAN-ROL-ENC", "nombre_oficial": "Rollos Manteles Encanto", "categoria": "Manteles", "cantidad": 4},

        # --- INSUMOS (Cuellos, Tendederos, Kit, Rollos Impresión, Ribbon, Cintas, Stretch) ---
        
        {"sku": "TEN-GEN", "nombre_oficial": "Tendederos", "categoria": "Insumos", "cantidad": 128},
        {"sku": "KIT-REP", "nombre_oficial": "Kit de Reparación", "categoria": "Insumos", "cantidad": 13},
        {"sku": "INS-ROL-IMP", "nombre_oficial": "Rollos de impresion (x500)", "categoria": "Insumos", "cantidad": 6},
        {"sku": "INS-RIB", "nombre_oficial": "Ribon", "categoria": "Insumos", "cantidad": 5},
        {"sku": "INS-CIN", "nombre_oficial": "Cintas", "categoria": "Insumos", "cantidad": 5},
        {"sku": "INS-STR-GRD", "nombre_oficial": "Stretch grandes (45cm)", "categoria": "Insumos", "cantidad": 7},
        {"sku": "INS-STR-PEQ", "nombre_oficial": "Stretch pequeños (30cm)", "categoria": "Insumos", "cantidad": 3},

        # --- EMPAQUES (Bolsas) ---
        {"sku": "INS-BOL-GRD", "nombre_oficial": "Bolsas grandes 18x24", "categoria": "Empaques", "cantidad": 3},
        {"sku": "INS-BOL-MED", "nombre_oficial": "Bolsas medianas 14*18", "categoria": "Empaques", "cantidad": 9},
        {"sku": "INS-BOL-PEQ", "nombre_oficial": "Bolsas pequeñas 10*14", "categoria": "Empaques", "cantidad": 5}
    ]
    
    for p in productos_iniciales:
        inventario_col.update_one(
            {"sku": p["sku"]}, 
            {"$set": {"categoria": p["categoria"], "nombre_oficial": p["nombre_oficial"]}}, 
            upsert=True
        )
        
    return {"ok": True, "mensaje": "¡Inventario y categorías sincronizados correctamente con los filtros!"}
