${ctx.format_authors()}. ${ctx.updated.year}. ${getattr(ctx, 'citation_name', ctx.__unicode__())}.
In: ${request.dataset.formatted_editors()|n} (eds.)
${request.dataset.description}.
${request.dataset.publisher_place}: ${request.dataset.publisher_name}.
(Available online at http://${request.dataset.domain}${request.resource_path(ctx)}, Accessed on ${h.datetime.date.today()}.)
