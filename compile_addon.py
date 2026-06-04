import os
import zipfile
import struct

def compile_po_to_mo(po_path, mo_path):
    """Compila un archivo textual .po de gettext en un archivo binario .mo."""
    messages = {}
    msgid = None
    msgstr = None
    
    with open(po_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    in_msgid = False
    in_msgstr = False
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('msgid "') and line.endswith('"'):
            in_msgid = True
            in_msgstr = False
            msgid = line[7:-1]
        elif line.startswith('msgstr "') and line.endswith('"'):
            in_msgid = False
            in_msgstr = True
            msgstr = line[8:-1]
            messages[msgid] = msgstr
        elif line.startswith('"') and line.endswith('"'):
            val = line[1:-1]
            if in_msgid:
                msgid += val
            elif in_msgstr:
                msgstr += val
                messages[msgid] = msgstr

    # Decodificar secuencias de escape del archivo PO
    unescaped_messages = {}
    for k, v in messages.items():
        try:
            # unicode-escape decodifica \n, \t, etc.
            k_unescaped = k.encode('utf-8').decode('unicode-escape')
            v_unescaped = v.encode('utf-8').decode('unicode-escape')
            unescaped_messages[k_unescaped] = v_unescaped
        except Exception:
            unescaped_messages[k] = v

    keys = sorted(unescaped_messages.keys())
    encoded_keys = [k.encode('utf-8') for k in keys]
    encoded_values = [unescaped_messages[k].encode('utf-8') for k in keys]
    
    offsets = []
    ids = b''
    strs = b''
    
    for k, v in zip(encoded_keys, encoded_values):
        offsets.append((len(ids), len(k), len(strs), len(v)))
        ids += k + b'\0'
        strs += v + b'\0'
        
    keystart = 7 * 4 + 16 * len(keys)
    valuestart = keystart + len(ids)
    
    koffsets = []
    voffsets = []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]
        
    packed_offsets = koffsets + voffsets
    header = struct.pack("Iiiiiii",
                         0x950412de,       # Magic (.mo format)
                         0,                 # Version
                         len(keys),         # Number of entries
                         7 * 4,             # Offset of key index
                         7 * 4 + len(keys) * 8, # Offset of value index
                         0, 0)              # Hash table size/offset
    
    os.makedirs(os.path.dirname(mo_path), exist_ok=True)
    with open(mo_path, 'wb') as f:
        f.write(header)
        f.write(struct.pack(f"{len(packed_offsets)}i", *packed_offsets))
        f.write(ids)
        f.write(strs)


def compile_translations():
    """Busca archivos .po en addon/locale y los compila a .mo."""
    addon_dir = "addon"
    locale_dir = os.path.join(addon_dir, "locale")
    if not os.path.exists(locale_dir):
        return
        
    print("Compilando catálogos de traducción (.po -> .mo)...")
    for root, dirs, files in os.walk(locale_dir):
        for file in files:
            if file.endswith(".po"):
                po_path = os.path.join(root, file)
                mo_path = po_path[:-3] + ".mo"
                print(f" -> Compilando: {po_path} a {mo_path}")
                try:
                    compile_po_to_mo(po_path, mo_path)
                except Exception as e:
                    print(f"Error al compilar {po_path}: {e}")


def compile_addon():
    addon_name = "dextop_whatsapp_voice-1.0.nvda-addon"
    
    # 0. Compilar catálogos de traducción de gettext antes de empaquetar
    compile_translations()
    
    # Lista de archivos a empaquetar en formato (ruta_local, ruta_en_zip)
    files_to_zip = []
    
    # 1. Agregar manifest.ini en la raíz del ZIP
    if os.path.exists("manifest.ini"):
        files_to_zip.append(("manifest.ini", "manifest.ini"))
    else:
        print("Error: manifest.ini no encontrado en el directorio actual.")
        return
        
    # 2. Agregar installTasks.py en la raíz del ZIP (si existe)
    if os.path.exists("installTasks.py"):
        files_to_zip.append(("installTasks.py", "installTasks.py"))
        
    # 3. Agregar contenidos del directorio local "addon"
    addon_dir = "addon"
    if os.path.exists(addon_dir):
        for root, dirs, files in os.walk(addon_dir):
            for file in files:
                # Omitir archivos fuentes .po de la empaquetación si se prefiere,
                # pero los empaquetaremos para cumplir con la transparencia en la tienda.
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, addon_dir)
                files_to_zip.append((full_path, rel_path))
    else:
        print("Error: El directorio local 'addon' no existe.")
        return

    # 4. Agregar contenidos del directorio local "doc"
    doc_dir = "doc"
    if os.path.exists(doc_dir):
        for root, dirs, files in os.walk(doc_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, ".")
                files_to_zip.append((full_path, rel_path))
        
    print(f"\nEmpaquetando complemento {addon_name}...")
    with zipfile.ZipFile(addon_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for full, rel in files_to_zip:
            print(f" -> Agregando: {rel}")
            zipf.write(full, rel)
            
    print(f"\n¡Compilación exitosa! Se ha creado el archivo: {os.path.abspath(addon_name)}")

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    compile_addon()
