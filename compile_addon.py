import os
import zipfile

def compile_addon():
    addon_name = "metavoice_desktop-1.0.nvda-addon"
    
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
                full_path = os.path.join(root, file)
                # La ruta en el ZIP NO debe llevar el prefijo "addon/"
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
        
    print(f"Empaquetando complemento {addon_name}...")
    with zipfile.ZipFile(addon_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for full, rel in files_to_zip:
            print(f" -> Agregando: {rel}")
            zipf.write(full, rel)
            
    print(f"\n¡Compilación exitosa! Se ha creado el archivo: {os.path.abspath(addon_name)}")

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    compile_addon()
