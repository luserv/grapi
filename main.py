"""
Script para autenticarse en Instagram y consultar seguidores con más de 1000 seguidores
"""
import os
import time
import random
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ChallengeRequired, TwoFactorRequired


def autenticar_instagram(username: str, password: str, session_file: str = "session.json"):
    """
    Autentica el usuario en Instagram usando instagrapi.

    Reutiliza la sesión guardada sin re-loguear si sigue viva. Solo hace
    login real cuando la sesión venció o no existe, reusando el mismo
    device/uuids para no parecer un dispositivo nuevo (eso dispara challenges).

    Args:
        username: Nombre de usuario de Instagram
        password: Contraseña de Instagram
        session_file: Archivo para guardar la sesión

    Returns:
        Client: Cliente autenticado de instagrapi
    """
    cl = Client()
    # Delay aleatorio incorporado entre requests (comportamiento más humano)
    cl.delay_range = [2, 5]

    # Cargar sesión guardada si existe
    session = None
    if os.path.exists(session_file):
        try:
            session = cl.load_settings(session_file)
        except Exception as e:
            print(f"⚠ No se pudo leer la sesión guardada: {e}")

    sesion_reutilizada = False
    if session:
        try:
            cl.set_settings(session)
            # Validar la sesión con una llamada ligera, sin forzar re-login
            cl.get_timeline_feed()
            sesion_reutilizada = True
            print("✓ Sesión reutilizada (sin re-login)")
        except LoginRequired:
            print("⚠ La sesión venció, re-logueando con el mismo dispositivo...")
            # Conservar uuids/device para que Instagram vea el mismo equipo
            old_uuids = cl.get_settings().get("uuids", {})
            cl.set_settings({})
            if old_uuids:
                cl.set_uuids(old_uuids)
            cl.delay_range = [2, 5]
        except Exception as e:
            print(f"⚠ No se pudo validar la sesión: {e}")

    if not sesion_reutilizada:
        try:
            cl.login(username, password)
            print("✓ Login exitoso")
        except TwoFactorRequired:
            # Si requiere 2FA, solicitar código
            verification_code = input("Ingresa el código de verificación 2FA: ")
            cl.login(username, password, verification_code=verification_code)
            print("✓ Login con 2FA exitoso")
        except ChallengeRequired:
            print("⚠ Instagram requiere verificación adicional (Challenge)")
            print("Por favor, verifica tu cuenta desde la app móvil o navegador")
            raise

    # En el camino de reuso de sesión se saltea login() (que setea cl.username);
    # lo garantizamos acá para que cl.username nunca quede vacío.
    if not getattr(cl, "username", None):
        cl.username = username

    # Guardar sesión para futuros usos
    cl.dump_settings(session_file)
    print(f"✓ Sesión guardada en {session_file}")

    return cl


def obtener_seguidores_con_mas_seguidores(cl: Client, min_seguidores: int = 1000):
    """
    Obtiene los seguidores del usuario autenticado que tienen más de min_seguidores seguidores
    
    Args:
        cl: Cliente autenticado de instagrapi
        min_seguidores: Número mínimo de seguidores requerido (default: 1000)
    
    Returns:
        list: Lista de usuarios que cumplen el criterio
    """
    print("\n📊 Obteniendo información de seguidores...")
    
    # Obtener información del usuario autenticado
    user_id = cl.user_id
    username = cl.username
    print(f"Usuario autenticado: @{username} (ID: {user_id})")
    
    # Obtener lista de seguidos
    print("Obteniendo lista de seguidos...")
    following = cl.user_following(user_id)
    total_followers = len(following)
    print(f"✓ Total de seguidos: {total_followers}")

    # Filtrar seguidos con más de min_seguidores seguidores
    print(f"\n🔍 Filtrando seguidos con más de {min_seguidores} seguidores...")
    seguidores_filtrados = []

    for idx, (follower_id, follower_data) in enumerate(following.items(), 1):
        try:
            # Obtener información completa del seguido
            user_info = cl.user_info(follower_id)
            follower_count = user_info.follower_count

            if follower_count >= min_seguidores:
                seguidores_filtrados.append({
                    'username': user_info.username,
                    'full_name': user_info.full_name,
                    'follower_count': follower_count,
                    'following_count': user_info.following_count,
                    'media_count': user_info.media_count,
                    'is_verified': user_info.is_verified,
                    'is_private': user_info.is_private,
                    'pk': user_info.pk
                })
                print(f"  [{idx}/{total_followers}] ✓ @{user_info.username}: {follower_count:,} seguidores")

            # Delay aleatorio entre requests para evitar rate limiting
            time.sleep(random.uniform(4, 8))

            # Pausa larga cada 30 usuarios
            if idx % 30 == 0:
                print(f"  Procesados: {idx}/{total_followers} | Encontrados: {len(seguidores_filtrados)}")
                print("  ⏸ Pausa para evitar rate limiting...")
                time.sleep(random.uniform(40, 70))

        except Exception as e:
            print(f"  ⚠ Error al obtener info del usuario {follower_id}: {e}")
            time.sleep(random.uniform(15, 30))
            continue
    
    return seguidores_filtrados


def mostrar_resultados(seguidores_filtrados: list):
    """
    Muestra los resultados de forma formateada
    
    Args:
        seguidores_filtrados: Lista de seguidores filtrados
    """
    print("\n" + "="*80)
    print(f"📈 RESULTADOS: {len(seguidores_filtrados)} seguidores con más de 1000 seguidores")
    print("="*80)
    
    if not seguidores_filtrados:
        print("No se encontraron seguidores que cumplan el criterio.")
        return
    
    # Ordenar por número de seguidores (descendente)
    seguidores_filtrados.sort(key=lambda x: x['follower_count'], reverse=True)
    
    print(f"\n{'#':<4} {'Usuario':<25} {'Seguidores':<15} {'Siguiendo':<12} {'Posts':<8} {'Verificado':<10}")
    print("-"*80)
    
    for idx, usuario in enumerate(seguidores_filtrados, 1):
        verified = "✓" if usuario['is_verified'] else ""
        private = "🔒" if usuario['is_private'] else ""
        print(f"{idx:<4} @{usuario['username']:<24} {usuario['follower_count']:>14,} "
              f"{usuario['following_count']:>11,} {usuario['media_count']:>7} {verified:<10}")
    
    print("\n" + "="*80)
    print(f"Total encontrado: {len(seguidores_filtrados)} seguidores")
    print("="*80)


def main():
    """
    Función principal
    """
    print("="*80)
    print("🔐 AUTENTICACIÓN EN INSTAGRAM")
    print("="*80)
    
    # Solicitar credenciales
    username = input("\nIngresa tu nombre de usuario de Instagram: ").strip()
    password = input("Ingresa tu contraseña: ").strip()
    
    if not username or not password:
        print("❌ Error: Usuario y contraseña son requeridos")
        return
    
    try:
        # Autenticar
        cl = autenticar_instagram(username, password)
        
        # Obtener seguidores con más de 1000 seguidores
        seguidores_filtrados = obtener_seguidores_con_mas_seguidores(cl, min_seguidores=1000)
        
        # Mostrar resultados
        mostrar_resultados(seguidores_filtrados)
        
        # Opción para guardar resultados en archivo
        guardar = input("\n¿Deseas guardar los resultados en un archivo? (s/n): ").strip().lower()
        if guardar == 's':
            nombre_archivo = f"seguidores_mas_1000_{username}.txt"
            with open(nombre_archivo, 'w', encoding='utf-8') as f:
                f.write(f"Seguidores de @{username} con más de 1000 seguidores\n")
                f.write("="*80 + "\n\n")
                for idx, usuario in enumerate(seguidores_filtrados, 1):
                    f.write(f"{idx}. @{usuario['username']}\n")
                    f.write(f"   Nombre: {usuario['full_name']}\n")
                    f.write(f"   Seguidores: {usuario['follower_count']:,}\n")
                    f.write(f"   Siguiendo: {usuario['following_count']:,}\n")
                    f.write(f"   Posts: {usuario['media_count']}\n")
                    f.write(f"   Verificado: {'Sí' if usuario['is_verified'] else 'No'}\n")
                    f.write(f"   Privado: {'Sí' if usuario['is_private'] else 'No'}\n")
                    f.write("\n")
            print(f"✓ Resultados guardados en {nombre_archivo}")
        
    except LoginRequired:
        print("❌ Error: Se requiere autenticación. Por favor, verifica tus credenciales.")
    except ChallengeRequired:
        print("❌ Error: Instagram requiere verificación adicional.")
        print("   Por favor, verifica tu cuenta desde la app móvil o navegador e intenta nuevamente.")
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
