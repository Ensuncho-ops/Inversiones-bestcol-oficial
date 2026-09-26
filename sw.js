// ═══════════════════════════════════════════════════════
// GuiaScan Backend — Felipe Ensuncho © 2026
// Servidor Node.js — Lógica completamente oculta
// ═══════════════════════════════════════════════════════

const express = require('express');
const cors    = require('cors');
const multer  = require('multer');
const pdf     = require('pdf-parse');
const path    = require('path');

const app  = express();
const PORT = process.env.PORT || 8080;

// ── Middleware ──
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Multer: archivos en memoria (no se guardan en disco)
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 20 * 1024 * 1024 } });

// ── Base de datos en memoria (se carga desde PDF o API) ──
// En producción puedes conectar una base de datos real aquí
let guias = {}; // { codigo: { destino, contenido, estado, hora } }

// ════════════════════════════════════════════
// API: Verificar guía escaneada
// POST /api/verificar  { codigo: "36395575137.1" }
// ════════════════════════════════════════════
app.post('/api/verificar', (req, res) => {
  const { codigo } = req.body;
  if (!codigo) return res.json({ ok: false, msg: 'Sin código' });

  const code = extraerCodigo(codigo);
  const g = guias[code];

  if (!g) {
    return res.json({ resultado: 'NO_ENCONTRADA', codigo: code, msg: 'No está en la lista' });
  }

  if (g.estado === 'rev') {
    return res.json({ resultado: 'DUPLICADA', codigo: code, msg: 'Ya fue revisada a las ' + g.hora, destino: g.destino, contenido: g.contenido });
  }

  // Marcar como revisada
  g.estado = 'rev';
  g.hora   = horaActual();

  return res.json({
    resultado:  'REVISADA',
    codigo:     code,
    destino:    g.destino  || '',
    contenido:  g.contenido|| '',
    hora:       g.hora
  });
});

// ════════════════════════════════════════════
// API: Obtener lista de guías
// GET /api/guias
// ════════════════════════════════════════════
app.get('/api/guias', (req, res) => {
  res.json({ guias });
});

// ════════════════════════════════════════════
// API: Importar PDF
// POST /api/importar-pdf  (multipart: archivo PDF)
// ════════════════════════════════════════════
app.post('/api/importar-pdf', upload.single('pdf'), async (req, res) => {
  if (!req.file) return res.json({ ok: false, msg: 'Sin archivo' });

  try {
    const data  = await pdf(req.file.buffer);
    const texto = data.text;
    const items = extraerDelPDF(texto);

    let agregadas = 0;
    items.forEach(({ code, destino, contenido }) => {
      if (!guias[code]) {
        guias[code] = { destino, contenido, estado: 'pen', hora: null };
        agregadas++;
      }
    });

    res.json({ ok: true, total: items.length, agregadas, msg: `${agregadas} guías nuevas agregadas` });
  } catch (err) {
    console.error(err);
    res.json({ ok: false, msg: 'Error leyendo el PDF' });
  }
});

// ════════════════════════════════════════════
// API: Agregar guías manualmente (texto)
// POST /api/importar-texto  { texto: "guia1\nguia2" }
// ════════════════════════════════════════════
app.post('/api/importar-texto', (req, res) => {
  const { texto } = req.body;
  if (!texto) return res.json({ ok: false, msg: 'Sin texto' });

  const lineas = texto.split(/[\n\r]+/).map(l => l.trim()).filter(Boolean);
  let agregadas = 0;
  lineas.forEach(linea => {
    const partes  = linea.split(/[,;\t]/);
    const code    = partes[0].trim();
    const destino = partes[1] ? partes[1].trim() : '';
    const contenido = partes[2] ? partes[2].trim() : '';
    if (code && !guias[code]) {
      guias[code] = { destino, contenido, estado: 'pen', hora: null };
      agregadas++;
    }
  });

  res.json({ ok: true, agregadas, msg: `${agregadas} guías agregadas` });
});

// ════════════════════════════════════════════
// API: Eliminar una guía
// DELETE /api/guias/:codigo
// ════════════════════════════════════════════
app.delete('/api/guias/:codigo', (req, res) => {
  const code = decodeURIComponent(req.params.codigo);
  if (guias[code]) { delete guias[code]; res.json({ ok: true }); }
  else res.json({ ok: false, msg: 'No existe' });
});

// ════════════════════════════════════════════
// API: Reiniciar escaneos
// POST /api/reiniciar
// ════════════════════════════════════════════
app.post('/api/reiniciar', (req, res) => {
  Object.keys(guias).forEach(c => { guias[c].estado = 'pen'; guias[c].hora = null; });
  res.json({ ok: true });
});

// ════════════════════════════════════════════
// API: Borrar todo
// POST /api/borrar-todo
// ════════════════════════════════════════════
app.post('/api/borrar-todo', (req, res) => {
  guias = {};
  res.json({ ok: true });
});

// ════════════════════════════════════════════
// API: Exportar CSV
// GET /api/exportar
// ════════════════════════════════════════════
app.get('/api/exportar', (req, res) => {
  const filas = ['Guia,Destino,Contenido,Estado,Hora'];
  Object.keys(guias).forEach(c => {
    const g = guias[c];
    filas.push([c, g.destino||'', g.contenido||'', g.estado==='rev'?'REVISADO':'PENDIENTE', g.hora||''].join(','));
  });
  res.setHeader('Content-Type', 'text/csv');
  res.setHeader('Content-Disposition', 'attachment; filename=guias.csv');
  res.send(filas.join('\n'));
});

// ════════════════════════════════════════════
// LÓGICA OCULTA — Extracción de código
// ════════════════════════════════════════════
function extraerCodigo(raw) {
  const s = raw.trim();
  const m1 = s.match(/\b(\d{9,13}\.\d{1,2})\b/);
  if (m1) return m1[1];
  if (/^\d{12,}$/.test(s)) {
    for (const key of Object.keys(guias)) {
      const base = key.includes('.') ? key.split('.')[0] : key;
      if (base.length >= 8 && s.includes(base)) return key;
    }
    if (s.length === 15 && s[0] === '7') return s.substring(1,12) + '.1';
    if (s[0] === '7' && s.length >= 12)  return s.substring(1,12) + '.1';
    if (/^\d{10,13}$/.test(s)) return s;
  }
  const m2 = s.match(/GUIA[:\s#]{0,5}(\d{8,13}(?:\.\d{1,2})?)/i);
  if (m2) return m2[1];
  const m3 = s.match(/(\d{6,}(?:\.\d{1,2})?)/);
  if (m3) return m3[1];
  return s;
}

// ════════════════════════════════════════════
// LÓGICA OCULTA — Extracción desde PDF
// ════════════════════════════════════════════
function extraerDelPDF(text) {
  const map = {};

  // ── PASO 1: Manifiesto (fuente más confiable para lista de guías) ──
  // Formato: "Nro: 1 Guia: 240050922464 Ciudad Destino: BOGOTA Valor de Recaudo: 129900"
  let m;
  const reManifest = /Nro:\s*\d+\s+Guia:\s*(\d{8,13}(?:\.\d{1,2})?)\s+Ciudad Destino:\s*([^\n\r]+?)\s+Valor/gi;
  while ((m = reManifest.exec(text)) !== null) {
    const code = m[1].trim(), dest = m[2].trim();
    if (!map[code]) map[code] = { destino: dest, contenido: '' };
  }
  // Sin "Valor" al final
  const reManifest2 = /Nro:\s*\d+\s+Guia:\s*(\d{8,13}(?:\.\d{1,2})?)/gi;
  while ((m = reManifest2.exec(text)) !== null) {
    if (!map[m[1]]) map[m[1]] = { destino: '', contenido: '' };
  }

  // ── PASO 2: Etiquetas individuales ──
  // Separar por cada etiqueta usando GUIA: como delimitador
  // También separar por "Durante el Dia" que es el encabezado de Interrapidísimo
  const separators = /(?=GUIA:|(?=Durante el Dia\s+\d))/gi;
  const blocks = text.split(separators).filter(b => b.trim().length > 20);

  blocks.forEach(block => {
    // Obtener número de guía del bloque
    let code = null;

    // Coordinadora: "GUIA:\n36395575137.1" o "GUIA: 36395575137.1"
    const gm1 = block.match(/GUIA:\s*[\r\n\s]*(\d{8,13}(?:\.\d{1,2})?)/i);
    if (gm1) code = gm1[1].trim();

    // Interrapidísimo: "GUIA: 240050922464" en línea
    if (!code) {
      const gm2 = block.match(/GUIA:\s*(\d{8,13})/i);
      if (gm2) code = gm2[1].trim();
    }

    if (!code) return;

    // Asegurar que el código esté en el map
    if (!map[code]) map[code] = { destino: '', contenido: '' };

    const products = [];

    // ── Coordinadora: * ID(XXXX)Nombre Producto X qty ──
    const reCoord = /\*\s*ID\(\d+\)([^\n\r*]{4,100})/gi;
    while ((m = reCoord.exec(block)) !== null) {
      const raw2 = m[1].trim();
      // Extraer cantidad si existe "X 1" al final
      const qmatch = raw2.match(/\s+X\s+(\d+)\s*$/i);
      const qty  = qmatch ? ' x' + qmatch[1] : '';
      const prod = raw2
        .replace(/\s+X\s+\d+\s*$/i, '')
        .replace(/\$[\d.,]+/g, '')
        .trim();
      // Excluir líneas que no son productos reales
      if (prod.length > 4 && prod.length < 100 &&
          !/envío?\s*prioritario/i.test(prod) &&
          !/^envo\s/i.test(prod)) {
        products.push(prod + qty);
      }
    }

    // ── Interrapidísimo: buscar tabla # PRODUCTO CANT ──
    if (products.length === 0) {
      // Buscar sección entre "# PRODUCTO CANT" y "www." o "Notas:" o fin
      const secMatch = block.match(/#\s*PRODUCTO\s+CANT\s*([\s\S]+?)(?:www\.|Notas:|Powered by|$)/i);
      if (secMatch) {
        const lines = secMatch[1].split(/[\n\r]+/);
        lines.forEach(line => {
          const l = line.trim();
          if (!l) return;
          if (/^\$/.test(l)) return;               // línea de precio
          if (/^\d+(\s+\d+)?$/.test(l)) return;    // solo números
          if (/^(PRODUCTO|CANT|#)$/i.test(l)) return; // encabezados
          if (l.length < 6 || l.length > 150) return;
          const clean = l
            .replace(/\$[\d.,]+.*/g, '')  // quitar precios
            .replace(/^\d+\s+/, '')        // quitar número de fila inicial
            .trim();
          if (clean.length > 5) products.push(clean);
        });
      }
    }

    // ── Fallback: buscar líneas con palabras clave de producto ──
    if (products.length === 0) {
      const reProd = /([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s]{3,}(?:Medidas?|Metros?|Talla|Abrigo|Tendedero|Protector|Silla|Cama|Juego|Set|Kit|Pack)[^$\n\r]{0,80})/g;
      while ((m = reProd.exec(block)) !== null) {
        const prod = m[1]
          .replace(/^(PRODUCTO\s+CANT\s*[\n\r]*)/i, '')
          .replace(/\$[\d.,]+.*/g, '')
          .trim();
        if (prod.length > 8 && prod.length < 120) products.push(prod);
      }
    }

    // Guardar contenido único, máximo 2 productos
    const contenido = [...new Set(products)].slice(0, 2).join(' | ');
    if (contenido && !map[code].contenido) {
      map[code].contenido = contenido;
    }
  });

  // ── PASO 3: Deduplicar — preferir código con .1 ──
  const result = {};
  Object.keys(map).forEach(code => {
    const base   = code.includes('.') ? code.split('.')[0] : code;
    const dotKey = base + '.1';
    const key    = map[dotKey] ? dotKey : code;
    if (!result[key]) {
      result[key] = { ...map[code] };
    } else {
      if (!result[key].destino   && map[code].destino)   result[key].destino   = map[code].destino;
      if (!result[key].contenido && map[code].contenido) result[key].contenido = map[code].contenido;
    }
  });

  return Object.keys(result).map(code => ({ code, ...result[code] }));
}

function horaActual() {
  return new Date().toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' });
}

// ── Iniciar servidor ──
app.listen(PORT, () => {
  console.log(`GuiaScan backend corriendo en puerto ${PORT}`);
});
