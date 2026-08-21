package com.ecommerce.aftersales.response;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

@Data
public class SupplementAfterSalesResponse {

    @JsonSerialize(using = ToStringSerializer.class)
    private Long ticketId;

    @JsonSerialize(using = ToStringSerializer.class)
    private Long sessionId;

    private String eventId;
    private String reviewRequestId;
    private Integer evidenceRevision;
    private Integer attachmentCount;
    private Boolean idempotent;
}
