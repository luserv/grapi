# Product

## Register

product

## Users

Un único usuario: el dueño del proyecto, que analiza su propia red de Instagram (a quién sigue y quién lo sigue). Es técnico, conoce la herramienta de memoria y la corre desde su máquina. No hay onboarding, ni explicaciones, ni público externo. El contexto de uso es una sesión de escritorio, concentrada, buscando una respuesta concreta ("quién de los que sigo tiene más de N seguidores", "ver los posts de tal cuenta").

## Product Purpose

Herramienta personal para inspeccionar y filtrar la red de seguidores/seguidos de una cuenta de Instagram vía la API privada (`instagrapi`). El usuario inicia sesión, elige analizar *following* o *followers* (propios o de un `target_username`), ve el progreso en vivo mientras se recorre la lista, y filtra los resultados en el cliente (públicos/privados/verificados, mínimo de seguidores, palabra clave en bio/nombre/usuario). Puede ordenar la tabla, exportar a CSV y abrir una galería de posts de cualquier cuenta. Éxito = responder rápido una pregunta sobre la red sin fricción ni esperas innecesarias en la UI.

## Brand Personality

Rápida, técnica, silenciosa. Tres palabras: **afilada, densa, sin ceremonia.** La interfaz es un instrumento de poder al estilo Linear/Raycast: prioriza densidad de información y velocidad de lectura por encima de la decoración. No celebra, no guía, no explica de más. Cada elemento existe porque ayuda a leer datos o a accionar sobre ellos. La única espera real (el fetch con rate-limit) se comunica con honestidad y precisión, nunca se disfraza.

## Anti-references

- **La estética oficial de Instagram**: gradientes púrpura/rosa, círculos de stories, degradados de marca. Esto analiza datos de IG pero no se parece a IG.
- **SaaS genérico**: hero con gradiente, grillas de tarjetas idénticas (icono + título + texto), ilustraciones corporativas, métricas gigantes con label chiquito.
- **Sobre-animación**: transiciones decorativas, bounce, efectos que distraen del trabajo.
- **Recargado**: exceso de color, sombras pesadas, glassmorphism decorativo, todo envuelto en cards.

## Design Principles

1. **Densidad sobre aire.** Es para alguien que quiere ver muchos datos a la vez. Tablas legibles y compactas antes que layouts espaciados y "respirados".
2. **Velocidad percibida.** La UI nunca bloquea: el progreso del fetch se muestra en vivo, los filtros y el orden son instantáneos en cliente, nada obliga a re-consultar.
3. **Honestidad sobre el costo.** El rate-limit de Instagram es real y lento; la interfaz lo refleja con claridad (progreso, conteos, errores legibles) en lugar de spinners vacíos o promesas falsas.
4. **Sin ceremonia.** Cero onboarding, cero copy de relleno, cero confirmaciones innecesarias. El usuario sabe lo que hace; la herramienta se aparta del camino.
5. **El dato es el héroe.** El cromo (bordes, fondos, acentos) se subordina al contenido. El color se usa para señalizar estado (verificado, privado, error), no para decorar.

## Accessibility & Inclusion

Nivel básico, por ser de uso propio: buen contraste de texto sobre fondo, foco de teclado siempre visible, y animaciones mínimas que respeten `prefers-reduced-motion`. Sin requisitos WCAG formales, pero sin descuidar la legibilidad ya que el uso es intensivo y prolongado.
