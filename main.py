"""
Script para autenticarse en Instagram y consultar seguidores con más de 1000 seguidores
"""
import os
import time
import random
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ChallengeRequired, TwoFactorRequired

from grapi_core.instagram import autenticar_instagram, obtener_usuarios


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
        
        # Obtener usuarios (seguidores o following)
        todos_los_usuarios = obtener_usuarios(cl, modo="following")
        
        # Filtrar a aquellos con más de 1000 seguidores
        seguidores_filtrados = [
            u for u in todos_los_usuarios if u.get("follower_count", 0) >= 1000
        ]
        
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
