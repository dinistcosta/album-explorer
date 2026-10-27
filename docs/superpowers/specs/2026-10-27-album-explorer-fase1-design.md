# Album Explorer — Fase 1: pesquisa, página da banda e página do álbum

Data: 2026-10-27

## Intenção

Album Explorer é um "museu de álbuns" na web. As pessoas chegam com os discos de que já gostam, pesquisam-nos, e ficam a conhecê-los a fundo: como foram feitos, por quem, que história têm. A partir daí, descobrem música parecida, mas sempre com a razão da ligação à vista (mesmo produtor, mesma cena, influência), como as placas de um museu que dizem "aluno de" ou "da mesma escola".

O objetivo a prazo é ter utilizadores reais: cobertura (discos pouco conhecidos também têm de ter uma página útil) e rapidez importam mais do que meia dúzia de páginas perfeitas.

**Agora, a fase 1 é uma demo para o portefólio no GitHub**, publicada online para que quem visitar o repositório possa abrir um link e experimentar: pesquisar qualquer disco e ver a página dele. A arquitetura fica pensada para utilizadores reais (cache, fontes isoladas numa camada própria, as duas línguas), porque é isso que mostra a qualidade do trabalho a quem lê o código. O que só importa com muito tráfego fica de fora. Sem uso comercial.

O produto completo cresce por fases (do documento original do autor):

1. Pesquisa e página do álbum com a história. **← este documento**
2. Ranking das faixas, tabelas de vendas e listas da crítica, descoberta de música parecida.
3. Concertos.
4. Reviews, notas e contribuições dos utilizadores (incluindo histórias e citações).
5. Contas, listas pessoais e publicação online.

## Objetivos da fase 1

- Pesquisar por banda ou álbum e chegar à página certa.
- **Página da banda**: história, discografia, membros, links oficiais.
- **Página do álbum**: a experiência de "abrir um vinil", com faixas, história, citações, créditos, prémios, links para ouvir e comprar.
- **Páginas de género**: discos de um género organizados por época.
- Site bilingue (português e inglês).
- Todos os dados vêm de fontes abertas e cada bloco mostra a fonte.
- Guardar os dados de forma a que a fase 2 (ligações entre discos) não exija refazer o modelo.
- **Publicado online** num alojamento gratuito ou quase, com o link no README.
- **README de portefólio**: o que é, capturas de ecrã, link da demo, decisões técnicas explicadas, como correr localmente.

## Não-objetivos (fase 1)

- Ranking de faixas, tabelas de vendas, listas da crítica (fase 2).
- Álbuns parecidos e ligações visíveis entre discos (fase 2; mas os dados ficam guardados já).
- Concertos (fase 3).
- Contas, reviews, notas, contribuições dos utilizadores (fases 4–5).
- Tocar música no site.
- Preparação para muito tráfego: processo que pré-carrega o catálogo, cópia própria do MusicBrainz, servidores dedicados para a fila de tarefas. A camada das fontes fica isolada para estas coisas poderem entrar mais tarde.
- Uso comercial (anúncios, afiliados). Os termos do Last.fm e do Discogs não o permitem sem acordo; a questão volta quando o site deixar de ser uma demo.

## Anti-objetivos (falha mesmo que funcione)

- Parecer o Spotify: feed de recomendações sem explicação, contadores de reproduções em destaque, scroll infinito, música a tocar sozinha, grelhas ordenadas só por popularidade.
- Texto inventado: nada de histórias ou citações geradas por IA. Uma ficha curta e verdadeira vale mais do que um texto convincente e errado.
- Copiar revistas: reviews e entrevistas não são copiadas. Citações curtas só com autor e fonte.
- Informação sem fonte.
- Depender de curadoria manual: o site tem de se alimentar sozinho.

## Abordagens consideradas

1. **Django com páginas geradas no servidor** — *escolhida.* Python no centro; o Django traz i18n, contas (fase 5), painel de administração e integração com PostgreSQL; HTML do servidor é bom para SEO, importante para um site que quer ser encontrado por quem pesquisa um disco. Custo: interface menos "app", irrelevante para um site de conteúdo.
2. **FastAPI (API) + React** — fica bem num portefólio "full-stack", mas são dois projetos, metade é JavaScript, e SEO exige trabalho extra.
3. **FastAPI com templates** — mais leve, mas contas, i18n e administração teriam de ser montadas à mão sem ganho.

O autor escolheu a 1. Pediu que as escolhas técnicas fossem feitas por quem constrói e explicadas à medida.

## Restrições

- **Limites das fontes**: MusicBrainz aceita **1 pedido/segundo** por IP e exige um User-Agent identificável (nome da app, versão, contacto). Discogs: 60 pedidos/min autenticado (token pessoal). Last.fm: chave de API, uso razoável. Wikipedia/Wikidata/Wikiquote: User-Agent identificável, sem limite rígido mas educado.
- Com utilizadores reais não se pode ir às fontes em cada visita: **cada entidade é buscada à primeira visita, guardada na base de dados e servida daí**, com atualização periódica em segundo plano.
- **Licenças**: texto da Wikipedia, Wikiquote e wiki do Last.fm é CC BY-SA — mostrar autoria/link e licença junto ao texto. Wikidata e MusicBrainz core são CC0. Imagens do Cover Art Archive e Wikimedia Commons: mostrar a fonte.

## Fontes de dados

| Dado | Fonte |
|---|---|
| Catálogo (bandas, álbuns, edições, faixas, durações) | MusicBrainz |
| Créditos (produtor, engenharia, mistura, músicos, estúdio) | MusicBrainz (relações) |
| Membros da banda, anos, instrumentos | MusicBrainz |
| Capas | Cover Art Archive |
| Foto da banda | Wikimedia Commons (via Wikidata, P18); senão, capa do disco mais conhecido |
| História do álbum / da banda | Wikipedia → wiki do Last.fm → ficha gerada a partir dos dados |
| Citações | Wikiquote; citações entre aspas dentro do artigo da Wikipedia (com a referência que o artigo dá) |
| Prémios e distinções | Wikidata (P166, com qualificadores de data/categoria) |
| Influências (guardar para a fase 2) | Wikidata (P737) |
| Géneros / estilos | MusicBrainz (genres), Discogs (styles), Last.fm (tags) |
| Popularidade (só para ordenar dentro de uma época) | Last.fm |
| Notas da edição, editora, formatos | Discogs |
| Links para ouvir | MusicBrainz (relações de URL: Spotify, Apple Music, YouTube, Bandcamp) |
| Links para comprar | Bandcamp (MusicBrainz); pesquisa do disco no Discogs Marketplace |

A ligação entre fontes faz-se por identificadores, não por nome: MusicBrainz → Wikidata (relação de URL) → artigos da Wikipedia por língua (sitelinks) e Wikiquote; MusicBrainz → Discogs (relação de URL). O Last.fm aceita MBID; quando falha, pesquisa por artista + título.

## Línguas

- Interface em português e inglês (i18n do Django, URLs com prefixo `/pt/` e `/en/`, escolha inicial pelo `Accept-Language`, seletor visível).
- História: artigo da Wikipedia na língua de quem lê; se não existir, o inglês com a indicação "disponível apenas em inglês" e link. **Sem tradução automática.** O mesmo para o Last.fm (a API aceita `lang`).
- A ficha gerada a partir dos dados usa modelos de frase nas duas línguas.

## Páginas

### Página inicial

A porta de entrada é a pesquisa: uma caixa grande no centro. Por baixo, discreto, algumas "salas" de género (etiquetas que levam às páginas de género). Sem feed, sem "em alta".

### Pesquisa

- Caixa única com sugestões à medida que se escreve, separadas em **Bandas** e **Álbuns**. **As sugestões vêm só da base de dados local**, nunca do MusicBrainz a cada tecla.
- Ao submeter (Enter), a página de resultados junta o local e a pesquisa no MusicBrainz (search API). Os resultados são guardados em cache, e as pesquisas repetidas não voltam ao MusicBrainz.
- Página de resultados: bandas em cima, depois álbuns como capas lado a lado ("caixote de vinis").
- Nos álbuns, mostrar só release groups do tipo álbum/EP. Ordenar por relevância, com desempate para os mais conhecidos (contagem de ouvintes do Last.fm, quando já existir em cache).

### Página da banda

- Topo: foto, nome, país, anos de atividade.
- História da banda (cadeia de fontes como no álbum).
- Discografia em capas, por ordem cronológica: primeiro álbuns de estúdio. EPs, ao vivo e compilações ficam em secções recolhidas.
- Membros, com anos e instrumentos.
- Links oficiais (site, redes sociais), vindos do MusicBrainz.
- Géneros como etiquetas clicáveis.

### Página do álbum (layout A, escolhido a partir do esboço)

Esboço de referência: `docs/superpowers/mockups/album-page-layout.html` (variante A).

1. **Topo**: capa grande à esquerda. O disco desliza para fora da capa ao carregar (e ao passar o rato). À direita: "Álbum · ano", título, banda (link), editora · géneros · nº de faixas · duração. Botões para ouvir e comprar.
2. **Faixas**: Lado A e Lado B em duas colunas, com duração.
3. **"Nas palavras da banda"**: uma ou duas citações, com quem disse e a fonte. Só aparece se houver.
4. **Encarte**: história em fundo cor de creme com textura de papel, com uma citação destacada a partir do texto, quando houver. Fonte e licença em rodapé.
5. **Coluna lateral**: créditos (produtor, mistura, engenharia, estúdio e local, músicos convidados) e prémios e distinções, cada um com a fonte.
6. **Outras edições**: uma linha discreta ("também editado como: Remaster 2011, Deluxe 20th Anniversary…").
7. Géneros como etiquetas clicáveis.

**Edição de referência**: dentro de um release group, usar a edição oficial mais antiga e o seu alinhamento de faixas.

**Lado A e Lado B**: vêm das posições de faixa de uma edição em vinil do mesmo release group (o MusicBrainz guarda "A1", "B1"…), desde que o alinhamento coincida com a edição de referência. *Decisão minha:* sem edição em vinil fiável, mostrar uma lista única "Alinhamento", sem lados inventados, porque dividir a meio seria informação falsa.

**Histórias, por ordem**:
1. Wikipedia (língua de quem lê, senão inglês com aviso). Mostrar a introdução e as secções sobre gravação/produção e receção, se existirem, com link para o artigo completo.
2. Wiki do Last.fm (resumo do álbum).
3. Ficha gerada a partir dos dados, em frases simples: "Gravado em 1994 nos estúdios X, em Lisboa. Produzido por Y. Editado pela Z, em vinil e CD." Inclui as notas da edição do Discogs, quando houver. Quando o disco só tem a ficha, mostra um espaço "Conheces a história deste disco?" (só marcador até à fase 4).

**Citações**:
- Wikiquote: citações da página do artista que mencionem o álbum ou as suas faixas, com a fonte que o Wikiquote indica.
- Wikipedia: passagens entre aspas no artigo do álbum atribuídas a um membro da banda ou ao produtor (nomes conhecidos dos créditos), mantendo a referência do artigo. A heurística deve ser conservadora: na dúvida sobre quem disse, não mostrar.

**Cor de destaque**: extraída da capa no servidor (cor dominante saturada). Se não tiver contraste suficiente sobre o fundo escuro (WCAG AA para texto grande), clarear até ter. É usada em rótulos, etiqueta do disco, links e realces. Guardar na base de dados.

**Links para ouvir**: Spotify, Apple Music, YouTube/YouTube Music, Bandcamp, a partir das relações de URL do MusicBrainz (do release group ou de qualquer edição). O botão de um serviço só aparece se houver link.

**Links para comprar**: Bandcamp (se houver) e "Procurar no Discogs" (pesquisa do disco no marketplace, para vinil, CD e usados).

### Página de género ("sala")

- Título e, se houver, uma descrição curta (wiki da tag no Last.fm ou Wikipedia), com fonte.
- Discos do género agrupados por década, como salas de uma exposição. Dentro de cada década, ordenados por popularidade (Last.fm `tag.getTopAlbums`), mas sem mostrar números.
- **Que géneros existem**: a lista de géneros do MusicBrainz é a oficial (é curada, não tem etiquetas como "seen live"). Etiquetas do Last.fm e estilos do Discogs só são usados quando correspondem a um género dessa lista (comparação normalizada do nome). Os URLs usam o slug do género do MusicBrainz.
- **Sala ainda incompleta**: os discos do Last.fm que ainda não estão na base de dados são resolvidos no MusicBrainz em segundo plano. A sala mostra os que já estão resolvidos e completa-se com o tempo. Na publicação, as salas ligadas da página inicial são pré-carregadas (ver "Dados de arranque").

## Estética

- Fundo escuro quase preto, encartes cor de creme com textura de papel, tipografia clássica (serifada para títulos e texto, monoespaçada para rótulos e metadados).
- A cor de destaque de cada álbum dá a cada página o seu tom.
- Tom de museu: textos como placas de exposição, nada de números de popularidade em destaque, nada de scroll infinito, nada a tocar sozinho.
- Funciona em telemóvel (uma coluna, margens de 16 px).
- Respeitar `prefers-reduced-motion` na animação do disco.

## Arquitetura (escolhas técnicas, decididas por quem constrói)

- **Django** (versão estável atual), templates do lado do servidor, **PostgreSQL**.
- **HTMX** para as sugestões da pesquisa e para preencher secções da página que chegam depois. JavaScript mínimo, sem framework, para a animação do vinil.
- **Fluxo de uma primeira visita**:
  1. Pedido síncrono mínimo ao MusicBrainz (release group + edição de referência + faixas). Mostra logo a página com capa, título e faixas.
  2. Enriquecimento em segundo plano (Wikipedia, Last.fm, Wikidata, Wikiquote, Discogs, cor de destaque, lados do vinil, créditos completos). As secções aparecem com um estado "a carregar" discreto e preenchem-se via HTMX.
  3. As visitas seguintes servem tudo da base de dados.
- **Fontes isoladas numa camada própria** (um cliente por fonte, com uma interface comum). Usa-se a API pública do MusicBrainz. Uma cópia própria do MusicBrainz pode entrar mais tarde trocando só o cliente.
- **Fila de tarefas guardada no PostgreSQL** (sem Redis), para a demo correr com uma base de dados e um processo de trabalho. Serve o enriquecimento e as atualizações periódicas (a cada 30 dias por entidade, quando é visitada com dados velhos).
- **Limitador de pedidos global** por fonte (MusicBrainz: 1/s, partilhado entre processos) e User-Agent identificável. Os pedidos de páginas visitadas têm prioridade sobre o trabalho de fundo. Respostas HTTP em cache bruta, para poder reprocessar sem voltar a pedir.
- **Painel de administração do Django** para ver e corrigir dados e forçar uma atualização. **As correções feitas à mão sobrevivem às atualizações automáticas**: cada campo ou bloco editado à mão é marcado e a atualização não lhe toca.

## Dados de arranque

Para a demo não abrir vazia, um comando de gestão (`manage.py seed`) carrega uma lista curta de discos e bandas, incluindo os discos de referência dos testes e os das salas ligadas na página inicial. Corre uma vez na publicação, respeitando os limites das fontes. Não há processo contínuo a pré-carregar o catálogo.

## Publicação

- Alojamento gratuito ou quase: um serviço web Python e um PostgreSQL gerido. Aceita-se que o site demore uns segundos a acordar na primeira visita.
- Configuração por variáveis de ambiente (chaves das APIs, base de dados, `DEBUG`), estáticos servidos pela própria app (por ex. WhiteNoise).
- Publicação automática a partir do `main` no GitHub, com os testes a correr antes (GitHub Actions).

## Modelo de dados (esboço)

Pensado para que a fase 2 só tenha de ler ligações que já existem:

- `Artist` (mbid, nome, país, anos, wikidata_id, discogs_id, foto)
- `Album` = release group (mbid, título, ano, tipo, artista, cor de destaque, edição de referência)
- `Release` = edição (mbid, título, data, país, formato, editora)
- `Track` (edição, posição, lado, título, duração, recording mbid)
- `Person` / reutilizar `Artist` para produtores, músicos e engenheiros (no MusicBrainz são todos artistas)
- `Credit` (álbum ou faixa, pessoa, papel, instrumento)
- `Place` (estúdios, com local) e `Credit` ligado a `Place` para "gravado em"
- `Membership` (banda, membro, anos, instrumentos)
- `Genre` e ligação a álbuns e bandas (com origem: MusicBrainz, Discogs ou Last.fm)
- `Story` (entidade, língua, texto, fonte, url, licença, data de obtenção)
- `Quote` (entidade, texto, autor, fonte, url, data)
- `Award` (entidade, prémio, categoria, ano, fonte)
- `Influence` (artista → artista, fonte) — guardado agora, mostrado na fase 2
- `ExternalLink` (entidade, tipo: ouvir/comprar/oficial, serviço, url)
- `SourceFetch` (fonte, chave, última obtenção, estado), para controlar atualizações

Todos os blocos de conteúdo guardam fonte, url e licença.

## Testes

- Testes automáticos (pytest + pytest-django). As chamadas às fontes são simuladas com respostas reais gravadas: nunca bater nas APIs reais nos testes.
- Cobrir em especial a lógica com regras: cadeia de fontes da história, escolha da edição de referência, deteção dos lados do vinil, extração de citações, contraste da cor de destaque, ficha gerada nas duas línguas.
- Um conjunto pequeno de discos de referência para verificar à mão: um muito conhecido (*Nevermind*), um português, um com artigo só em inglês, um sem Wikipedia nenhuma, um sem edição em vinil.

## Decidido pelo autor

- Utilizadores reais em primeiro lugar; cobertura e rapidez importam.
- Site bilingue, português e inglês.
- Histórias pela cadeia Wikipedia → Last.fm → ficha gerada a partir dos dados; sem IA a inventar texto.
- Prémios e distinções na fase 1; tabelas de vendas e listas da crítica na fase 2.
- Citações dos artistas, automáticas, sem curadoria manual.
- Página da banda com história, álbuns e o resto.
- Página do álbum com o layout A.
- "Museu de álbuns", não um Spotify: ligações explicadas, tom de exposição.
- Django.
- Para já, uma demo de portefólio, publicada online para se poder experimentar; sem uso comercial.

## Decisões de quem constrói (para o autor rever)

- API pública do MusicBrainz, com a camada das fontes isolada para trocar mais tarde.
- Sugestões da pesquisa só da base de dados local; MusicBrainz só ao submeter.
- Lista de géneros do MusicBrainz como oficial; salas completam-se com o tempo.
- Correções manuais sobrevivem às atualizações.
- Fila de tarefas no PostgreSQL, sem Redis; dados de arranque com um comando em vez de um processo contínuo.

- Sem tradução automática; o texto em inglês aparece com aviso.
- Sem lados A/B inventados quando não há edição em vinil.
- Links de compra na fase 1: só Bandcamp e pesquisa no Discogs.
- Ordenação das salas de género por década, e por popularidade dentro de cada década (sem números).
- Primeira visita: dados mínimos síncronos e o resto preenchido em segundo plano.

## Deixado ao construtor

- Biblioteca da fila de tarefas e do limitador de pedidos; biblioteca de extração de cor.
- Detalhes da heurística de citações (dentro da regra "na dúvida, não mostrar").
- Tipografia exata (o esboço usa Playfair Display, Source Serif 4 e IBM Plex Mono).
- Ambiente de desenvolvimento (por ex. PostgreSQL via Docker Compose).
- Serviço de alojamento concreto (a propor ao autor antes de criar contas).
- Lista exata dos discos de arranque.
